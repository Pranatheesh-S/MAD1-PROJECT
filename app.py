from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, Patient, Doctor, Department, Appointment, Treatment
from datetime import datetime, date, time, timedelta

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hospital.db'
app.config['SECRET_KEY'] = 'your_secret_key_12345'
db.init_app(app)

# --- Flask-Login Setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    # Check the session to see if we are loading a Doctor or a Patient
    role = session.get('role')
    if role == 'doctor':
        return db.session.get(Doctor, int(user_id))
    else:
        # Default to Patient
        return Patient.query.get(int(user_id))

# --- Authentication Routes (PATIENT) ---

@app.route('/')
def home():
    if current_user.is_authenticated:
        if session.get('role') == 'doctor':
            return redirect(url_for('doctor_dashboard'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        patient = Patient.query.filter_by(email=email).first()
        
        if patient and patient.check_password(password):
            if patient.is_blacklisted:
                flash('Your account has been suspended. Please contact support.', 'danger')
                return redirect(url_for('login'))
            
            # CRITICAL: Set role before login
            session['role'] = 'patient'
            login_user(patient)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        
        existing = Patient.query.filter_by(email=email).first()
        if existing:
            flash('Email already registered', 'warning')
        else:
            new_patient = Patient(name=name, email=email)
            new_patient.set_password(password)
            db.session.add(new_patient)
            db.session.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

# --- Authentication Routes (DOCTOR) ---

@app.route('/doctor', methods=['GET', 'POST'])
def doctor_login():
    if current_user.is_authenticated:
        if session.get('role') == 'doctor':
            return redirect(url_for('doctor_dashboard'))
        else:
            flash('You are logged in as a patient. Please logout first.', 'warning')
            return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        # Print for debugging
        print(f"Attempting login for: {email}") 
        
        doctor = Doctor.query.filter_by(email=email).first()

        if doctor:
            # Print found doctor
            print(f"Doctor found: {doctor.name}") 
            if doctor.check_password(password):
                if doctor.is_blacklisted:
                    flash('Your account has been suspended.', 'danger')
                    return redirect(url_for('doctor_login'))

                # Explicitly clear any old session data
                session.clear() 
                
                # Set new session data
                session['role'] = 'doctor'
                session.permanent = True # Ensure session sticks
                login_user(doctor)
                
                print("Login successful, redirecting...")
                flash(f'Welcome back, Dr. {doctor.name}', 'success')
                return redirect(url_for('doctor_dashboard'))
            else:
                print("Password check failed")
                flash('Invalid password', 'danger')
        else:
            print("No doctor found with that email")
            flash('Invalid email', 'danger')

    return render_template('doctor_login.html')

# --- REMOVED doctor_signup ROUTE HERE ---

@app.route('/logout')
@login_required
def logout():
    session.pop('role', None) # Clear the role
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

# --- Dashboard Routes (PATIENT) ---

@app.route('/dashboard')
@login_required
def dashboard():
    if session.get('role') == 'doctor':
         return redirect(url_for('doctor_dashboard'))
         
    departments = Department.query.all()
    upcoming_appts = Appointment.query.filter(
        Appointment.patient_id == current_user.id,
        Appointment.date >= date.today(),
        Appointment.status == 'Booked'
    ).order_by(Appointment.date, Appointment.time).all()
    
    return render_template('dashboard.html', 
                           patient=current_user, 
                           departments=departments, 
                           appointments=upcoming_appts)

@app.route('/department/<int:dept_id>')
@login_required
def department_detail(dept_id):
    department = Department.query.get_or_404(dept_id)
    active_doctors = Doctor.query.filter_by(department_id=dept_id, is_blacklisted=False).all()
    return render_template('department_detail.html', department=department, doctors=active_doctors) 

@app.route('/doctor/profile/<int:doctor_id>') 
@login_required
def doctor_detail(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    if doctor.is_blacklisted:
        flash('This doctor is no longer available.', 'warning')
        return redirect(url_for('dashboard'))
    return render_template('doctor_detail.html', doctor=doctor)

@app.route('/book/<int:doctor_id>', methods=['GET', 'POST'])
@login_required
def book_appointment(doctor_id):
    if session.get('role') == 'doctor':
        flash("Doctors cannot book appointments for themselves.", "warning")
        return redirect(url_for('doctor_dashboard'))

    doctor = Doctor.query.get_or_404(doctor_id)
    if doctor.is_blacklisted:
        flash('This doctor is no longer available for booking.', 'warning')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        try:
            selected_slot = request.form.get('selected_slot')
            if not selected_slot:
                flash('Please select a valid time slot.', 'danger')
                return redirect(url_for('book_appointment', doctor_id=doctor_id))

            date_str, time_str = selected_slot.split('_')
            appt_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            appt_time = datetime.strptime(time_str, '%H:%M:%S').time()

            existing = Appointment.query.filter_by(
                doctor_id=doctor.id, 
                date=appt_date, 
                time=appt_time, 
                status='Booked').first()
            
            if existing:
                flash('This slot has just been booked. Please select another.', 'danger')
                return redirect(url_for('book_appointment', doctor_id=doctor_id))

            new_appt = Appointment(
                patient_id=current_user.id,
                doctor_id=doctor.id,
                date=appt_date,
                time=appt_time,
                status='Booked'
            )
            db.session.add(new_appt)
            db.session.commit()
            flash(f'Appointment with {doctor.name} on {date_str} at {appt_time.strftime("%I:%M %p")} booked!', 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            flash(f'An error occurred: {e}', 'danger')
            db.session.rollback()
            return redirect(url_for('book_appointment', doctor_id=doctor_id))

    standard_slots = [time(8, 0), time(16, 0)] 
    today = date.today()
    date_range = [today + timedelta(days=d) for d in range(7)]
    
    existing_appts = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date.in_(date_range),
        Appointment.status == 'Booked'
    ).all()
    booked_slots = set((appt.date, appt.time) for appt in existing_appts)
    
    availability_data = []
    for day in date_range:
        slots_for_day = {'date': day, 'slots': []}
        for slot_time in standard_slots:
            is_booked = (day, slot_time) in booked_slots
            slots_for_day['slots'].append({'time': slot_time, 'is_booked': is_booked})
        availability_data.append(slots_for_day)
    
    return render_template('book_appointment.html', doctor=doctor, availability_data=availability_data)

@app.route('/appointment/cancel/<int:appt_id>', methods=['POST'])
@login_required
def cancel_appointment(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    # Allow patient to cancel own, or doctor to cancel their patient's
    is_patient_owner = (session.get('role') == 'patient' and appt.patient_id == current_user.id)
    is_doctor_owner = (session.get('role') == 'doctor' and appt.doctor_id == current_user.id)

    if not (is_patient_owner or is_doctor_owner):
        flash('Permission denied.', 'danger')
        return redirect(url_for('home'))
        
    appt.status = 'Cancelled'
    db.session.commit()
    flash('Appointment has been cancelled.', 'success')
    return redirect(url_for('home'))

@app.route('/history')
@login_required
def patient_history():
    if session.get('role') != 'patient':
        return redirect(url_for('home'))

    past_appts = Appointment.query.filter(
        Appointment.patient_id == current_user.id,
        Appointment.status.in_(['Completed', 'Cancelled'])
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all()
    return render_template('patient_history.html', appointments=past_appts)

# --- Dashboard Routes (DOCTOR - NEW) ---

@app.route('/doctor/dashboard')
@login_required
def doctor_dashboard():
    # Security check: Ensure strictly a doctor is accessing this
    if session.get('role') != 'doctor':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    # Get appointments for this doctor
    upcoming_appts = Appointment.query.filter(
        Appointment.doctor_id == current_user.id,
        Appointment.date >= date.today(),
        Appointment.status == 'Booked'
    ).order_by(Appointment.date, Appointment.time).all()

    return render_template('doctor_dashboard.html', 
                           doctor=current_user, 
                           appointments=upcoming_appts)

# --- ADMIN ROUTES ---

@app.route('/admin-434345ndfsdj') 
def admin_dashboard():
    doctors = Doctor.query.order_by(Doctor.name).all()
    patients = Patient.query.order_by(Patient.name).all()
    upcoming_appts = Appointment.query.filter(
        Appointment.date >= date.today(),
        Appointment.status == 'Booked'
    ).order_by(Appointment.date, Appointment.time).all()
    
    return render_template('admin_dashboard.html',
                           doctors=doctors,
                           patients=patients,
                           appointments=upcoming_appts)

@app.route('/admin/doctor/add', methods=['GET', 'POST'])
def admin_add_doctor():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        specialization = request.form.get('specialization')
        department_id = request.form.get('department_id')
        experience_str = request.form.get('experience')
        password = request.form.get('password') # <--- Get password from form

        existing = Doctor.query.filter_by(email=email).first()
        if existing:
            flash('A doctor with this email already exists.', 'danger')
            departments = Department.query.all()
            return render_template('add_doctor.html', departments=departments)
        
        experience = int(experience_str) if experience_str else None

        new_doctor = Doctor(
            name=name,
            email=email,
            specialization=specialization,
            department_id=int(department_id),
            experience=experience
        )
        # Use the provided password, or default to '123' if empty
        new_doctor.set_password(password if password else '123') 
        
        db.session.add(new_doctor)
        db.session.commit()
        flash(f'Dr. {new_doctor.name} has been added successfully.', 'success')
        return redirect(url_for('admin_dashboard'))

    departments = Department.query.all()
    return render_template('add_doctor.html', departments=departments)

@app.route('/admin/doctor/edit/<int:doctor_id>', methods=['GET', 'POST'])
def admin_edit_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    departments = Department.query.all()

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        specialization = request.form.get('specialization')
        department_id = request.form.get('department_id')
        experience_str = request.form.get('experience')

        existing_email_user = Doctor.query.filter_by(email=email).first()
        if existing_email_user and existing_email_user.id != doctor.id:
            flash('This email is already in use by another doctor.', 'danger')
            return render_template('edit_doctor.html', doctor=doctor, departments=departments)

        doctor.name = name
        doctor.email = email
        doctor.specialization = specialization
        doctor.department_id = int(department_id)
        doctor.experience = int(experience_str) if experience_str else None

        try:
            db.session.commit()
            flash(f'Details for Dr. {doctor.name} updated successfully.', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating record: {e}', 'danger')

    return render_template('edit_doctor.html', doctor=doctor, departments=departments)

@app.route('/admin/patient/edit/<int:patient_id>', methods=['GET', 'POST'])
def admin_edit_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        age_str = request.form.get('age')
        gender = request.form.get('gender')

        existing_email_user = Patient.query.filter_by(email=email).first()
        if existing_email_user and existing_email_user.id != patient.id:
            flash('This email is already in use by another patient.', 'danger')
            return render_template('edit_patient.html', patient=patient)

        patient.name = name
        patient.email = email
        patient.age = int(age_str) if age_str else None
        patient.gender = gender

        try:
            db.session.commit()
            flash(f'Details for {patient.name} updated successfully.', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating record: {e}', 'danger')

    return render_template('edit_patient.html', patient=patient)

@app.route('/admin/patient/delete/<int:patient_id>', methods=['POST'])
def admin_delete_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    Appointment.query.filter_by(patient_id=patient.id).delete()
    db.session.delete(patient)
    db.session.commit()
    flash(f'Patient {patient.name} and their history have been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/doctor/delete/<int:doctor_id>', methods=['POST'])
def admin_delete_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    Appointment.query.filter_by(doctor_id=doctor.id).delete()
    db.session.delete(doctor)
    db.session.commit()
    flash(f'Dr. {doctor.name} and their appointments have been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/doctor/blacklist/<int:doctor_id>', methods=['POST'])
def admin_blacklist_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    doctor.is_blacklisted = True
    db.session.commit()
    flash(f'Dr. {doctor.name} has been blacklisted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/doctor/whitelist/<int:doctor_id>', methods=['POST'])
def admin_whitelist_doctor(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    doctor.is_blacklisted = False
    db.session.commit()
    flash(f'Dr. {doctor.name} has been restored.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/patient/blacklist/<int:patient_id>', methods=['POST'])
def admin_blacklist_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    patient.is_blacklisted = True
    db.session.commit()
    flash(f'Patient {patient.name} has been blacklisted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/patient/whitelist/<int:patient_id>', methods=['POST'])
def admin_whitelist_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    patient.is_blacklisted = False
    db.session.commit()
    flash(f'Patient {patient.name} has been restored.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/patient/history/view/<int:patient_id>')
def admin_patient_history_view(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    history = Appointment.query.filter(
        Appointment.patient_id == patient.id
    ).order_by(Appointment.date.desc()).all()
    return render_template('admin_patient_history.html', patient=patient, history=history)

# --- RUN / DEMO DATA ---

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Demo data setup
        if not Department.query.first():
            print("Creating demo data...")
            dept1 = Department(name='Cardiology', description='Heart issues.')
            dept2 = Department(name='Oncology', description='Cancer treatment.')
            dept3 = Department(name='General', description='General health.')
            db.session.add_all([dept1, dept2, dept3])
            db.session.commit()

            # Doctors now have passwords! (default: 'doctor123')
            doc1 = Doctor(name='Dr. Abcde', email='abcde@hospital.com', specialization='Cardiologist', department=dept1, experience=10)
            doc1.set_password('doctor123')
            
            doc2 = Doctor(name='Dr. Pqrst', email='pqrst@hospital.com', specialization='Cardiologist', department=dept1, experience=5)
            doc2.set_password('doctor123')

            doc3 = Doctor(name='Dr. Mnop', email='mnop@hospital.com', specialization='Medical Oncologist', department=dept2, experience=8)
            doc3.set_password('doctor123')

            db.session.add_all([doc1, doc2, doc3])
            
            demo_patient = Patient(name='John Doe', email='john@test.com', age=30, gender='Male')
            demo_patient.set_password('123')
            db.session.add(demo_patient)
            db.session.commit()
            
            appt1 = Appointment(patient=demo_patient, doctor=doc3, date=date(2025, 9, 24), time=time(8, 12), status='Booked')
            db.session.add(appt1)
            db.session.commit()
            print("Demo data created with Doctor password 'doctor123' and Patient password '123'.")

    app.run(debug=True)