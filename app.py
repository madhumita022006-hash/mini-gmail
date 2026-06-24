from flask import Flask, request, session, render_template, redirect, url_for, flash
import mysql.connector
from mysql.connector import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Use a strong secret key

# Configurations
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database connection
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="Me_myself#07",
        database="mini_gmail",
        port=3306
    )

# Allowed file checker
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Home Route (Login Page)
@app.route('/')
def home():
    return render_template('login.html')

# Register Page (GET)
@app.route('/register')
def register_page():
    return render_template('register.html')

# Register (POST)
@app.route('/register', methods=['POST'])
def register():
    name = request.form.get('name')
    email = request.form.get('email')
    password = generate_password_hash(request.form.get('password'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO Users (Name, Email, Password) VALUES (%s, %s, %s)',
            (name, email, password)
        )
        conn.commit()
        flash("Registered successfully. Please login.")
    except IntegrityError:
        flash("Email already registered.")
        return redirect(url_for('register_page'))
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('home'))

# Login Route
@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT * FROM Users WHERE Email = %s', (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user and check_password_hash(user['Password'], password):
        session['user_id'] = user['UserID']
        session['user_name'] = user['Name']
        return redirect(url_for('dashboard'))
    else:
        flash("Invalid email or password.")
        return redirect(url_for('home'))

# Dashboard
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('home'))
    return render_template('dashboard.html', user_name=session.get('user_name'))

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# Inbox
@app.route('/inbox')
def inbox():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT e.EmailID, e.Subject, e.Body, e.Timestamp, 
               u.Name AS SenderName, u.Email AS SenderEmail
        FROM Email e
        JOIN Users u ON e.SenderID = u.UserID
        WHERE e.ReceiverID = %s
        ORDER BY e.Timestamp DESC
    ''', (user_id,))
    emails = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('inbox.html', emails=emails)

# Sent Mail
@app.route('/sent')
def sent():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT e.Subject, e.Body, e.Timestamp, 
               u.Name AS ReceiverName, u.Email AS ReceiverEmail
        FROM Email e
        JOIN Users u ON e.ReceiverID = u.UserID
        WHERE e.SenderID = %s
        ORDER BY e.Timestamp DESC
    ''', (user_id,))
    emails = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('sent.html', emails=emails)

# Send Email (with prefill support)
@app.route('/send', methods=['GET', 'POST'])
def send_email():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        receiver_email = request.form.get('receiver_email')
        subject = request.form.get('subject')
        body = request.form.get('body')
        attachment_filename = None

        # File upload
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and allowed_file(file.filename):
                attachment_filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], attachment_filename))

        # Lookup receiver
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT UserID FROM Users WHERE Email = %s', (receiver_email,))
        receiver = cursor.fetchone()

        if not receiver:
            flash('Receiver not found.')
            cursor.close()
            conn.close()
            return redirect(url_for('send_email'))

        # Insert email
        cursor.execute('''
            INSERT INTO Email (SenderID, ReceiverID, Subject, Body, Attachment) 
            VALUES (%s, %s, %s, %s, %s)
        ''', (session['user_id'], receiver['UserID'], subject, body, attachment_filename))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Email sent successfully.')
        return redirect(url_for('dashboard'))

    # For GET request, get prefill values from query parameters
    receiver_email = request.args.get('receiver_email', '')
    subject = request.args.get('subject', '')
    body = request.args.get('body', '')

    return render_template('send_email.html', 
                           receiver_email=receiver_email,
                           subject=subject,
                           body=body)

# Reply to an Email: redirects to compose with pre-filled form
@app.route('/reply/<int:email_id>', methods=['GET'])
def reply_email(email_id):
    if 'user_id' not in session:
        return redirect(url_for('home'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT e.Subject, e.Body, u.Email AS SenderEmail
        FROM Email e
        JOIN Users u ON e.SenderID = u.UserID
        WHERE e.EmailID = %s
    ''', (email_id,))
    email = cursor.fetchone()
    cursor.close()
    conn.close()

    if not email:
        flash('Email not found.')
        return redirect(url_for('inbox'))

    # Prepare subject with "Re: " prefix if not already there
    subject = email['Subject']
    if not subject.lower().startswith('re:'):
        subject = 'Re: ' + subject

    # Prepare the body with quoted original email (optional)
    body = f"\n\n--- Original Message ---\n{email['Body']}"

    # Redirect to compose page with query parameters
    return redirect(url_for('send_email',
                            receiver_email=email['SenderEmail'],
                            subject=subject,
                            body=body))

# View Contacts
@app.route('/contacts')
def contacts():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT u.Name, u.Email
        FROM Contact c
        JOIN Users u ON c.ContactUserID = u.UserID
        WHERE c.UserID = %s
    ''', (user_id,))
    contacts = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('contacts.html', contacts=contacts)

# Delete Email from Inbox
@app.route('/delete/<int:email_id>', methods=['POST'])
def delete_email(email_id):
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user_id = session['user_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Confirm the email exists and is received by the current user
    cursor.execute('SELECT * FROM Email WHERE EmailID = %s AND ReceiverID = %s', (email_id, user_id))
    email = cursor.fetchone()

    if not email:
        flash("You are not authorized to delete this email or it doesn't exist.")
        cursor.close()
        conn.close()
        return redirect(url_for('inbox'))

    # Proceed to delete the email
    cursor.execute('DELETE FROM Email WHERE EmailID = %s', (email_id,))
    conn.commit()

    cursor.close()
    conn.close()

    flash("Email deleted successfully.")
    return redirect(url_for('inbox'))

# Run App
if __name__ == '__main__':
    app.run(debug=True)
