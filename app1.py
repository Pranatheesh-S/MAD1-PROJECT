from flask import Flask, render_template, request, redirect, url_for, flash
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
login_manager.login_view = 'login' # Redirect to login page if user is not authenticated
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return Patient.query.get(int(user_id))

# --- Authentication Routes ---

@app.route('/')
def home():
    if current_user.is_authenticated:
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
            
            # --- MODIFICATION: Check if patient is blacklisted ---
            if patient.is_blacklisted:
                flash('Your account has been suspended. Please contact support.', 'danger')
                return redirect(url_for('login'))
            
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
            new_patient.set_password(password) # Use the hashing method
            db.session.add(new_patient)
            db.session.commit()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

# --- Dashboard Routes (from Wireframe) ---

@app.route('/dashboard')
@login_required
def dashboard():
    # Get departments for the list
    departments = Department.query.all()
    
    # Get upcoming appointments
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
    
    # --- MODIFICATION: Filter out blacklisted doctors ---
    active_doctors = [doc for doc in department.doctors if not doc.is_blacklisted]
    
    return render_template('department_detail.html', 
                           department=department, 
                           doctors=active_doctors) # Pass the filtered list

@app.route('/doctor/<int:doctor_id>')
@login_required
def doctor_detail(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)

    # --- MODIFICATION: Prevent viewing a blacklisted doctor ---
    if doctor.is_blacklisted:
        flash('This doctor is no longer available.', 'warning')
        return redirect(url_for('dashboard'))
    
    return render_template('doctor_detail.html', doctor=doctor)


@app.route('/book/<int:doctor_id>', methods=['GET', 'POST'])
@login_required
def book_appointment(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)

    # --- MODIFICATION: Prevent booking with a blacklisted doctor ---
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

    # --- GET Request Logic ---
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
        slots_for_day = {
            'date': day,
            'slots': []
        }
        for slot_time in standard_slots:
            is_booked = (day, slot_time) in booked_slots
            slots_for_day['slots'].append({
                'time': slot_time,
                'is_booked': is_booked
            })
        availability_data.append(slots_for_day)
    
    return render_template('book_appointment.html', 
                           doctor=doctor, 
                           availability_data=availability_data)


@app.route('/appointment/cancel/<int:appt_id>', methods=['POST'])
@login_required
def cancel_appointment(appt_id):
    appt = Appointment.query.get_or_404(appt_id)
    
    if appt.patient_id != current_user.id:
        flash('You do not have permission to cancel this appointment.', 'danger')
        return redirect(url_for('dashboard'))
    
    appt.status = 'Cancelled'
    db.session.commit()
    flash('Appointment has been cancelled.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/history')
@login_required
def patient_history():
    past_appts = Appointment.query.filter(
        Appointment.patient_id == current_user.id,
        Appointment.status.in_(['Completed', 'Cancelled'])
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all()
    
    return render_template('patient_history.html', appointments=past_appts)


# --- vvv ADMIN ROUTES vvv ---

@app.route('/admin-434345ndfsdj') # The secret URL
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

# --- THIS IS THE NEW ROUTE THAT FIXES THE ERROR ---
@app.route('/admin/doctor/add', methods=['GET', 'POST'])
def admin_add_doctor():
    if request.method == 'POST':
        # Get data from form
        name = request.form.get('name')
        email = request.form.get('email')
        specialization = request.form.get('specialization')
        department_id = request.form.get('department_id')
        experience_str = request.form.get('experience')

        # Validate unique email
        existing = Doctor.query.filter_by(email=email).first()
        if existing:
            flash('A doctor with this email already exists.', 'danger')
            # Fetch departments again for re-rendering the form
            departments = Department.query.all()
            return render_template('add_doctor.html', departments=departments)
        
        # Handle optional experience field
        experience = int(experience_str) if experience_str else None

        # Create new doctor
        new_doctor = Doctor(
            name=name,
            email=email,
            specialization=specialization,
            department_id=int(department_id),
            experience=experience
        )
        
        db.session.add(new_doctor)
        db.session.commit()
        
        flash(f'Dr. {new_doctor.name} has been added successfully.', 'success')
        return redirect(url_for('admin_dashboard'))

    # --- GET Request ---
    # Fetch departments for the dropdown
    departments = Department.query.all()
    return render_template('add_doctor.html', departments=departments)
# --- ^^^ THIS IS THE NEW ROUTE ^^^ ---

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
    patient = Patient.query.get_or_44(patient_id)
    patient.is_blacklisted = False
    db.session.commit()
    flash(f'Patient {patient.name} has been restored.', 'success')
    return redirect(url_for('admin_dashboard'))

# --- ^^^ ADMIN ROUTES ^^^ ---


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # --- Optional: Add Demo Data ---
        if not Department.query.first():
            print("Creating demo data...")
            # Create Departments
            dept1 = Department(name='Cardiology', description='Specializing in heart-related issues.')
            dept2 = Department(name='Oncology', description='Dedicated to the diagnosis, treatment, and care of patients with cancer.')
            dept3 = Department(name='General', description='General health checkups and primary care.')
            db.session.add_all([dept1, dept2, dept3])
            db.session.commit()

            # Create Doctors
            doc1 = Doctor(name='Dr. Abcde', email='abcde@hospital.com', specialization='Cardiologist', department=dept1, experience=10)
            doc2 = Doctor(name='Dr. Pqrst', email='pqrst@hospital.com', specialization='Cardiologist', department=dept1, experience=5)
            doc3 = Doctor(name='Dr. Mnop', email='mnop@hospital.com', specialization='Medical Oncologist', department=dept2, experience=8)
            db.session.add_all([doc1, doc2, doc3])
            
            # Create a demo patient
            demo_patient = Patient(name='Pqrst', email='pqrst@test.com', age=30, gender='Male')
            demo_patient.set_password('123') # Password is '123'
            db.session.add(demo_patient)
            db.session.commit()
            
            # Create demo appointments
            appt1 = Appointment(patient=demo_patient, doctor=doc3, date=date(2025, 9, 24), time=time(8, 12), status='Booked')
            appt2 = Appointment(patient=demo_patient, doctor=doc1, date=date(2025, 8, 10), time=time(10, 0), status='Completed')
            
            # Add a booked appointment for testing the new grid
            appt_booked = Appointment(patient=demo_patient, doctor=doc1, date=date.today() + timedelta(days=2), time=time(8, 0), status='Booked')

            db.session.add_all([appt1, appt2, appt_booked])
            db.session.commit()
            
            # Create demo treatment for past appointment
            treat1 = Treatment(appointment=appt2, diagnosis='Abnormal Heartbeats', prescription='Exercise daily', notes='Patient is recovering well.')
            db.session.add(treat1)
            db.session.commit()
            print("Demo data created. Log in with: pqrst@test.com / 123")

    app.run(debug=True)