from flask import Flask, render_template, url_for, request, redirect, flash, session
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import re
from datetime import datetime, timedelta
from flask_limiter import Limiter
import MySQLdb.cursors
from decimal import Decimal
import smtplib
# from dateutil.relativedelta import relativedelta
# from werkzeug.utils import secure_filename

app=Flask(__name__)

app.secret_key= "mwihoko_saccoSessions"
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Gkn23668174.'
app.config['MYSQL_DB'] = 'mwihoko_sacco'

mysql = MySQL(app)
limiter = Limiter(app)

def get_member_details(member_id):
    """Fetch member details including savings and membership duration."""
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("""
        SELECT savings, DATEDIFF(CURRENT_DATE, join_date) as membership_days
        FROM members
        WHERE id = %s
    """, (member_id,))
    member = cur.fetchone()
    cur.close()
    return member

def check_membership_duration(member_id):
    """Check if the member has been a member for at least 6 months."""
    member = get_member_details(member_id)
    return member['membership_days'] >= 180

def check_savings(member_id):
    """Get the savings of the member."""
    member = get_member_details(member_id)
    return member['savings']

def check_loan_repayment():
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    # Get loans that are past due
    cur.execute("""
        SELECT id, member_id, amount FROM loans 
        WHERE due_month < NOW() AND status = 'active'
    """)
    overdue_loans = cur.fetchall()

    for loan in overdue_loans:
        # Deduct from member's savings first
        cur.execute("SELECT savings FROM members WHERE id = %s", (loan['member_id'],))
        member_savings = cur.fetchone()['savings']

        if member_savings >= loan['amount']:
            # Deduct the full amount from member's savings
            cur.execute("UPDATE members SET savings = savings - %s WHERE id = %s", (loan['amount'], loan['member_id']))
            cur.execute("UPDATE loans SET status = 'paid' WHERE id = %s", (loan['id'],))
        else:
            # If not enough savings, deduct all savings
            remaining_loan = loan['amount'] - member_savings
            cur.execute("UPDATE members SET savings = 0 WHERE id = %s", (loan['member_id'],))

            # If the loan is still not paid, mark it as defaulted
            if remaining_loan > 0:
                cur.execute("UPDATE loans SET status = 'defaulted' WHERE id = %s", (loan['id'],))

    mysql.connection.commit()
    cur.close()

def check_loan_eligibility(member_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Get member's savings, membership duration, and active loans
    cur.execute("""
        SELECT 
            m.savings,
            DATEDIFF(CURRENT_DATE, m.join_date) as membership_days,
            COUNT(l.id) as active_loans
        FROM members m
        LEFT JOIN loans l ON m.id = l.member_id AND l.status = 'active'
        WHERE m.id = %s
        GROUP BY m.id
    """, (member_id,))
    
    result = cur.fetchone()
    cur.close()

    if not result:
        return False, "Member not found."

    savings = result['savings']
    membership_days = result['membership_days']
    active_loans = result['active_loans']

    # Check eligibility criteria
    if membership_days < 180:
        return False, "You must be a member for at least 6 months."
    
    if active_loans > 0:
        return False, "You have an active loan."

    # Maximum loan amount is 90% of savings
    max_loan = savings * Decimal('0.90')
    return True, max_loan

def has_active_loans(member_id):
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Check for active loans
    cur.execute("""
        SELECT COUNT(*) as active_loans_count 
        FROM loans 
        WHERE status = 'active' AND member_id = %s
    """, (member_id,))
    
    result = cur.fetchone()
    cur.close()

    return result['active_loans_count'] > 0

def is_valid_kra_pin(pin):
    pin = pin.upper()
    
    if len(pin) == 11 and pin[0].isalpha() and pin[-1].isalpha() and pin[1:10].isdigit() and pin.isalnum():
        return True
    return False

def is_valid_phone(phone):
    if phone.startswith('+254') and len(phone) == 13 and phone[4] in '17' and phone[5:].isdigit():
        return True
    elif phone.startswith('0') and len(phone) == 10 and phone[1:].isdigit():  # Allow any valid number starting with 0
        return True
    return False

def is_valid_id_number(id_num):
    if len(id_num) == 8 and id_num.isdigit():
        return True
    return False

def is_valid_email(email):
    regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    if re.match(regex, email):
        return True
    return False

def is_valid_name(full_name):
    # Allow spaces, hyphens, and apostrophes in the name
    for char in full_name:
        if not (char.isalpha() or char == " " or char == "-" or char == "'"):
            return False
    return True

def generate_membership_number():
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) FROM members")
    result = cur.fetchone()
    count = result[0] if result else 0
    cur.close()
    return "MWH%04d" % (count + 1)

@app.route('/')
def index():
    return render_template('/index.html')

@app.route('/about_us')
def about_us():
    return render_template('/about.html')

@app.route('/benefits')
def benefits():
    return render_template('/benefits.html')

@app.route('/contact_us', methods=['GET', 'POST'])
def contact_us():
    if request.method == "POST":
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cur.execute("""
                    INSERT INTO messages (name, email, message) 
                    VALUES (%s, %s, %s)""",(name, email, message))
        mysql.connection.commit()
        
        flash('Message sent successfully!', 'success')
        return redirect(url_for('contact_us'))
    
    return render_template('/contact_us.html')

@app.route('/sign_in', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def sign_in():
    if request.method == 'POST':
        membership_number = request.form['membership_number']
        password = request.form['password']
        # First, check if the user is an admin by querying the admins table
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cur.execute("SELECT * FROM admins WHERE username = %s", (membership_number,))
        admin = cur.fetchone()

        if admin and check_password_hash(admin['password'], password):
            # If admin, store admin session data and redirect to admin dashboard
            session['admin_id'] = admin['id']
            return redirect(url_for('admin_members'))  # Admin Dashboard
            
        # If not an admin, check the members table
        cur.execute("SELECT * FROM members WHERE membership_number = %s", (membership_number,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user['password'], password):
            # If member, store member session data and redirect to personal details
            session['user_id'] = user['id']
            session['membership_number'] = user['membership_number']

            session['user'] = user

            # Check loan eligibility and active loans
            eligible = check_loan_eligibility(user['id'])
            active_loans = has_active_loans(session['user_id'])

            # Store eligibility and loan status in session
            session['loan_eligible'] = eligible
            session['has_active_loans'] = active_loans

            flash('You have successfully signed in!', 'success')
            return redirect(url_for('view_personal_details')) 
            
        flash('Invalid credentials', 'error')

    return render_template('signin.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
            # Get form data
            full_name = request.form['full_name']
            id_number = request.form['id_number']
            phone = request.form['phone']
            email = request.form['email']
            occupation = request.form['occupation']
            kra_pin = request.form['kra_pin']
            password = request.form['password']
            confirm_password = request.form['confirm_password']

            # Validate input
            if not all([is_valid_kra_pin(kra_pin), 
                        is_valid_phone(phone), 
                        is_valid_id_number(id_number),
                        is_valid_email(email),
                        is_valid_name(full_name)]):
                flash('Invalid input format', 'error')
                return redirect(url_for('signup'))
            
            if password != confirm_password:
                flash('Passwords do not match', 'error')
                return redirect(url_for('signup'))

            if len(password) < 8:
                flash('Password must be at least 8 characters long', 'error')
                return redirect(url_for('signup'))

            # Generate membership number and password
            membership_number = generate_membership_number()
            hashed_password  = generate_password_hash(password)  # Initially set to ID number

            cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cur.execute("""
                INSERT INTO members (
                    membership_number, full_name, id_number, phone_number, email,
                    occupation, kra_pin, password, join_date, savings
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), 0)
            """, (
                membership_number, full_name, id_number, phone, email,
                occupation, kra_pin, hashed_password 
            ))
            
            mysql.connection.commit()
            member_id = cur.lastrowid
            
            cur.close()
            flash(f'Registration successful! Your membership number is {membership_number}. Please wait for admin approval (less than 24 hours).', 'success')
            return redirect(url_for('sign_in'))

    return render_template('signup.html')

                ########
                #member routes
@app.route('/view_personal_details', methods=['GET', 'POST'])
def view_personal_details():
    if 'user_id' not in session:
        return redirect(url_for('signin'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':
        # Get updated details from the form
        new_email = request.form.get('email')
        new_phone = request.form.get('phone_number')
        new_occupation = request.form.get('occupation')

        # Update the member's details in the database
        cur.execute("""
                UPDATE members
                SET email = COALESCE(%s, email),
                    phone_number = COALESCE(%s, phone_number),
                    occupation = COALESCE(%s, occupation)
                WHERE id = %s
            """, (new_email, new_phone, new_occupation, session['user_id']))
        mysql.connection.commit()

        flash('Your personal details have been updated successfully!', 'success')
        return redirect(url_for('view_personal_details'))

    # Fetch current user details
    cur.execute("""
                SELECT membership_number, full_name, id_number, phone_number, email, 
                occupation, kra_pin, join_date, DATEDIFF(CURRENT_DATE, join_date) AS membership_days
                FROM members
                WHERE id = %s""", (session['user_id'],))
    user = cur.fetchone()
    cur.close()

    return render_template('member/view_personal_details.html', user=user)

@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('signin'))

    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    # Fetch the current user's details
    cur.execute("SELECT password FROM members WHERE id = %s", (session['user_id'],))
    user = cur.fetchone()

    # Verify the current password
    if user and check_password_hash(user['password'], current_password):
        if new_password == confirm_password:
            hashed_new_password = generate_password_hash(new_password)
            cur.execute("""
                UPDATE members 
                SET password = %s 
                WHERE id = %s
            """, (hashed_new_password, session['user_id']))
            mysql.connection.commit()
            flash('Your password has been changed successfully!', 'success')
        else:
            flash('New passwords do not match.', 'error')
    else:
        flash('Current password is incorrect.', 'error')

    cur.close()
    return redirect(url_for('view_personal_details'))

@app.route('/view_loan_balance', methods=['GET'])
def view_loan_balance():
    if 'user_id' not in session:
        return redirect(url_for('signin'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Fetch loan details
    cur.execute("""
        SELECT id, amount, amount_paid, (amount - amount_paid) AS balance, start_month, due_month
        FROM loans
        WHERE member_id = %s AND status = 'active'
    """, (session['user_id'],))
    loan = cur.fetchone()

    if loan:
        cur.execute("""
            SELECT amount_paid, payment_date, remaining_balance
            FROM loan_payments
            WHERE loan_id = %s
            ORDER BY  remaining_balance ASC
        """, (loan['id'],))
        payment_history = cur.fetchall()

    # Fetch loan deductions
    cur.execute("SELECT amount_deducted, date_added FROM loan_deductions WHERE loan_id = %s", (loan['id'],))
    loan_deductions = cur.fetchall()

    cur.close()

    return render_template('member/view_loan_balance.html', payments=payment_history, loan=loan, loan_deductions=loan_deductions)

@app.route('/notifications')
def view_notifications():
    if 'user_id' not in session:
        return redirect(url_for('signin'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("""
        SELECT message, date_added
        FROM notifications
        ORDER BY date_added DESC
    """)
    notifications = cur.fetchall()
    cur.close()

    return render_template('member/notifications.html', notifications=notifications)

@app.route('/savings_summary', methods=['GET'])
def savings_summary():
    if 'user_id' not in session:
        return redirect(url_for('signin'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Fetch total savings
    cur.execute("SELECT savings FROM members WHERE id = %s", (session['user_id'],))
    total_savings = cur.fetchone()['savings']

    # Fetch deposit history
    cur.execute("""SELECT amount AS amount, date_added FROM savings_deposits WHERE member_id = %s ORDER BY date_added DESC""", (session['user_id'],))
    deposits = cur.fetchall()

    cur.close()

    return render_template('member/savings_summary.html', total_savings=total_savings, deposits=deposits)

@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'user_id' not in session:
        return redirect(url_for('signin'))
    
    if request.method == 'POST':
        deposit_amount = Decimal(request.form.get('amount'))
        mandatory_savings_threshold = 250  # First Ksh 250 to savings each month
        minimum_deposit = 50
        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        if deposit_amount < minimum_deposit:
            flash(f'Minimum deposit amount is Ksh{minimum_deposit}.', 'error')
            return redirect(url_for('deposit'))

        if deposit_amount > 100000:
            flash(f'Maximum deposit amount per day is Ksh100,000.', 'error')
            return redirect(url_for('deposit'))

        # Get user's savings and loan details
        cur.execute("SELECT savings, cumulative_savings FROM members WHERE id = %s", (session['user_id'],))
        member = cur.fetchone()
        current_cumulative_savings = member['cumulative_savings'] 
        # if member else 0

        # Check if the user has an active loan
        cur.execute("SELECT id, amount, amount_paid FROM loans WHERE member_id = %s AND status = 'active'", (session['user_id'],))
        loan = cur.fetchone()
        
        cur.execute("""
            SELECT id, loan_id, remaining_balance
            FROM loan_payments
            WHERE loan_id = %s
            ORDER BY payment_date DESC
            LIMIT 1
        """, (session['user_id'],))
        loan_payment = cur.fetchone()
        

        # Step 1: Allocate first Ksh 250 to savings if cumulative savings < threshold
        amount_to_savings = 0
        if current_cumulative_savings < mandatory_savings_threshold:
            savings_needed = mandatory_savings_threshold - current_cumulative_savings
            amount_to_savings = min(savings_needed, deposit_amount)

            cur.execute("UPDATE members SET savings = savings + %s, cumulative_savings = cumulative_savings + %s WHERE id = %s",
                        (amount_to_savings, amount_to_savings, session['user_id']))
            deposit_amount -= amount_to_savings

        # Record the savings transaction
        if amount_to_savings > 0:
            cur.execute("""
                INSERT INTO savings_deposits (member_id, amount, date_added)
                VALUES (%s, %s, NOW())
            """, (session['user_id'], amount_to_savings))

        # Step 2: Handle remaining amount (repay loan or add to savings)
        if loan:
            # Allocate remaining deposit to loan repayment
            loan_id = loan['id']
            amount_to_repay = min(deposit_amount, Decimal(loan_payment['remaining_balance']))

            cur.execute("""
                INSERT INTO loan_payments (loan_id, amount_paid, payment_date, remaining_balance) 
                VALUES (%s, %s, NOW(), %s)
            """, (loan_id, amount_to_repay, loan_payment['remaining_balance'] - amount_to_repay))
            
            # Update the amount_paid in the loan table by calculating the sum of all payments
            cur.execute("""
                SELECT SUM(amount_paid) AS total_paid
                FROM loan_payments
                WHERE loan_id = %s
            """, (loan_id,))
            total_paid = cur.fetchone()['total_paid']
            
            cur.execute("""
                UPDATE loans SET amount_paid = %s WHERE id = %s
            """, (total_paid, loan_id))

            deposit_amount -= amount_to_repay

        # Step 3: If there's remaining deposit, add it to savings
        if deposit_amount > 0:
            cur.execute("UPDATE members SET savings = (savings + %s) WHERE id = %s",
                        (deposit_amount, session['user_id']))
            cur.execute("""
                INSERT INTO savings_deposits (member_id, amount, date_added)
                VALUES (%s, %s, NOW())
            """, (session['user_id'], deposit_amount))

        # Commit all the changes
        mysql.connection.commit()
        cur.close()

        flash('Deposit successful!', 'success')
        return redirect(url_for('deposit'))
    
    return render_template('member/deposit.html')


@app.route('/apply_loan', methods=['POST','GET'])
def apply_loan():
    if 'user_id' not in session:
        return redirect(url_for('signin'))

    if request.method == 'POST':
        amount = float(request.form.get('amount'))

        cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        # Check membership duration
        if not check_membership_duration(session['user_id']):
            flash('To apply for a loan ,you must be an active member for more than 6 months.', 'error')
            return redirect(url_for('apply_loan'))

        # Get member's savings
        savings = check_savings(session['user_id'])

        if amount <= 0:
            flash('Loan amount must be greater than zero.', 'error')
            return redirect(url_for('apply_loan'))

        # Check if the loan amount is valid (90% of member's savings)
        if amount > savings * Decimal(0.90):
            flash('Loan amount cannot exceed 90% of your savings.', 'error')
            return redirect(url_for('apply_loan'))

        # Calculate interest and set loan details
        interest = amount * 0.075
        total_loan = amount + interest
        today = datetime.now()
        due_date = (today.replace(day=1) + timedelta(days=13 * 30)).replace(day=1)  # Adjust to the first of the month

        cur.execute("""
            INSERT INTO loans (member_id, amount, start_month, due_month, status) 
            VALUES (%s, %s, %s, %s, %s)
        """, (session['user_id'], total_loan, today.strftime('%Y-%m-%d'), due_date.strftime('%Y-%m-%d'), 'active'))
        mysql.connection.commit()
        cur.close()
        
        flash('Loan applied successfully!', 'success')
        return redirect(url_for('apply_loan'))
    return render_template('member/apply_loan.html')

                                #####
                            # Admin routes
@app.route('/admin/loan_status_report', methods=['GET'])
def loan_status_report():
    if 'admin_id' not in session:
        return redirect(url_for('signin'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch loan statuses
    cur.execute("""
        SELECT l.id, m.membership_number, l.amount, l.amount_paid, (l.amount - l.amount_paid) AS balance,
               l.status, l.start_month, l.due_month
        FROM loans l
        JOIN members m ON l.member_id = m.id
        ORDER BY l.status, l.due_month ASC
    """)
    loans = cur.fetchall()

    # Calculate total loan amount
    total_loans = sum(loan['amount'] for loan in loans)

    cur.close()

    return render_template(
        'admin/loan_status_report.html', loans=loans, total_loans=total_loans)

@app.route('/admin/savings_summary_report', methods=['GET'])
def savings_summary_report():
    if 'admin_id' not in session:
        return redirect(url_for('signin'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch savings summary for all members
    cur.execute("""
        SELECT membership_number, full_name, savings
        FROM members
        ORDER BY savings DESC
    """)
    savings_summary = cur.fetchall()

    # Calculate total savings
    total_savings = sum(member['savings'] for member in savings_summary)

    cur.close()

    return render_template('admin/savings_summary_report.html', savings_summary=savings_summary, total_savings=total_savings)

@app.route('/admin/deposit_activity_report', methods=['GET'])
def deposit_activity_report():
    if 'admin_id' not in session:
        return redirect(url_for('signin'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch deposit activity
    cur.execute("""
        SELECT m.membership_number, m.full_name, sd.amount, sd.date_added
        FROM savings_deposits sd
        JOIN members m ON sd.member_id = m.id
        ORDER BY sd.date_added DESC
    """)
    deposits = cur.fetchall()

    # Calculate total deposits
    total_deposits = sum(deposit['amount'] for deposit in deposits)

    cur.close()

    return render_template(
        'admin/deposit_activity_report.html', deposits=deposits,total_deposits=total_deposits)

@app.route('/admin/messages_report', methods=['GET', 'POST'])
def messages_report():
    if 'admin_id' not in session:
        return redirect(url_for('signin'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':
        # Reply to a message
        receiver_email = request.form['email']  # Receiver's email
        reply_message = request.form['reply_message']
        sender_email = 'gideonn660@gmail.com'  # Company's email address

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login('gideonn660@gmail.com','olpvnfefxnmzvqca')
        message = f"Subject: Reply from Mwihoko Sacco \n\n {reply_message}"


        server.sendmail(sender_email, receiver_email, message)
        server.quit()

        # Update the message status to 'replied'
        message_id = request.form['message_id']
        cur.execute("""
            UPDATE messages
            SET status = 'read'
            WHERE id = %s
        """, (message_id,))
        mysql.connection.commit()
        cur.close()

        return redirect(url_for('messages_report'))
    # Fetch unread messages
    cur.execute("""
        SELECT id,name, email, message,status
        FROM messages
        ORDER BY status
    """)
    messages = cur.fetchall()
    cur.close()

    return render_template('admin/messages_report.html', messages=messages)

@app.route('/admin/members', methods=['GET'])
def admin_members():
    if 'admin_id' not in session:
        return redirect(url_for('signin'))
    
    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    
    # Fetch all members
    cur.execute("""
        SELECT id, membership_number, full_name, join_date
        FROM members
        ORDER BY full_name
    """)
    members = cur.fetchall()

    # Calculate total members
    total_members = len(members)
    
    cur.close()
    
    return render_template('admin/admin_members.html',members=members,total_members=total_members)

@app.route('/admin/member/<int:member_id>', methods=['GET'])
def admin_member_reports(member_id):
    if 'admin_id' not in session:
        return redirect(url_for('signin'))

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch member details
    cur.execute("""
        SELECT id, membership_number, full_name, savings
        FROM members
        WHERE id = %s
    """, (member_id,))
    member = cur.fetchone()

    if not member:
        return "Member not found", 404

    # Fetch loan details for the member
    cur.execute("""
        SELECT id, amount, amount_paid, (amount - amount_paid) AS balance, status, start_month, due_month
        FROM loans
        WHERE member_id = %s
        ORDER BY status, due_month ASC
    """, (member_id,))
    loans = cur.fetchall()

    # Fetch deposit activity for the member
    cur.execute("""
        SELECT amount, date_added
        FROM savings_deposits
        WHERE member_id = %s
        ORDER BY date_added DESC
    """, (member_id,))
    deposits = cur.fetchall()

    # Fetch loan repayment details
    repayments = []
    if loans:
        cur.execute("""
            SELECT lp.loan_id, lp.amount_paid, lp.payment_date, lp.remaining_balance, l.id AS loan_id
            FROM loan_payments lp
            JOIN loans l ON lp.loan_id = l.id
            WHERE l.member_id = %s
            ORDER BY lp.payment_date DESC
        """, (member_id,))
        repayments = cur.fetchall()

    cur.close()

    return render_template('admin/admin_member_reports.html',member=member,loans=loans,deposits=deposits,repayments=repayments)

@app.route('/admin/notifications', methods=['GET', 'POST'])
def admin_notifications():
    if 'admin_id' not in session:
        return redirect(url_for('signin'))  # Redirect to sign-in if admin is not logged in

    cur = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':
        # Get the form data (message)
        message = request.form.get('message')

        # Insert the new notification into the database
        cur.execute("""
            INSERT INTO notifications (message,date_added)
            VALUES (%s,NOW())""", (message,))
        mysql.connection.commit()

    # Fetch all notifications to display
    cur.execute("""
        SELECT message, date_added
        FROM notifications
        ORDER BY date_added DESC""")
    notifications = cur.fetchall()
    cur.close()

    return render_template('admin/admin_notifications.html', notifications=notifications)

                    #######
                    #common routes
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('sign_in'))

if __name__ == "__main__":
    app.run(debug=True)
