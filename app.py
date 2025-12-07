from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, Patient, Doctor, Department, Appointment, Treatment, DoctorAvailability
from datetime import datetime, date, time, timedelta
from sqlalchemy import or_ 
import json 

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///hospital.db'
app.config['SECRET_KEY'] = 'your_secret_key_12345'
db.init_app(app)

# ---------------------------------------------------------------------------
# Flask-Login Configuration
# ---------------------------------------------------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    """
    Reloads the user object from the user ID stored in the session.
    Distinguishes between Doctor and Patient based on the session role.
    """
    role = session.get('role')
    if role == 'doctor':
        return db.session.get(Doctor, int(user_id))
    else:
        return db.session.get(Patient, int(user_id))

# ---------------------------------------------------------------------------
# Patient Authentication Routes
# ---------------------------------------------------------------------------

@app.route('/')
def home():
    """
    Root route. Redirects users to their respective dashboards if logged in,
    or to the login page if unauthenticated.
    """
    if current_user.is_authenticated:
        if session.get('role') == 'doctor':
            return redirect(url_for('doctor_dashboard'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles patient login. Checks credentials and blacklisting status.
    """
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        patient = Patient.query.filter_by(email=email).first()
        
        if patient and patient.check_password(password):
            if patient.is_blacklisted:
                flash('Your account has been suspended.', 'danger')
                return redirect(url_for('login'))
            
            session['role'] = 'patient'
            login_user(patient)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Handles new patient registration.
    """
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

# ---------------------------------------------------------------------------
# Doctor Authentication Routes
# ---------------------------------------------------------------------------

@app.route('/doctor', methods=['GET', 'POST'])
def doctor_login():
    """
    Handles doctor login. Enforces distinct session management to prevent
    role conflicts between patients and doctors.
    """
    if current_user.is_authenticated:
        if session.get('role') == 'doctor':
            return redirect(url_for('doctor_dashboard'))
        else:
            flash('You are logged in as a patient. Please logout first.', 'warning')
            return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        doctor = Doctor.query.filter_by(email=email).first()

        if doctor:
            if doctor.check_password(password):
                if doctor.is_blacklisted:
                    flash('Your account has been suspended.', 'danger')
                    return redirect(url_for('doctor_login'))

                # Clear previous session data and establish doctor session
                session.clear() 
                session['role'] = 'doctor'
                session.permanent = True 
                login_user(doctor)
                
                flash(f'Welcome back, Dr. {doctor.name}', 'success')
                return redirect(url_for('doctor_dashboard'))
            else:
                flash('Invalid password', 'danger')
        else:
            flash('Invalid email', 'danger')

    return render_template('doctor_login.html')

@app.route('/logout')
@login_required
def logout():
    """
    Logs out the current user and clears role data from the session.
    """
    session.pop('role', None)
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

# ---------------------------------------------------------------------------
# Patient Dashboard & Booking Routes
# ---------------------------------------------------------------------------

@app.route('/dashboard')
@login_required
def dashboard():
    """
    Main patient dashboard. Displays departments and upcoming appointments.
    """
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
    """
    Displays details of a specific department and lists active doctors.
    """
    department = db.get_or_404(Department, dept_id)
    active_doctors = Doctor.query.filter_by(department_id=dept_id, is_blacklisted=False).all()
    return render_template('department_detail.html', department=department, doctors=active_doctors) 

@app.route('/doctor/profile/<int:doctor_id>') 
@login_required
def doctor_detail(doctor_id):
    """
    Displays public profile of a doctor.
    """
    doctor = db.get_or_404(Doctor, doctor_id)
    if doctor.is_blacklisted:
        flash('This doctor is no longer available.', 'warning')
        return redirect(url_for('dashboard'))
    return render_template('doctor_detail.html', doctor=doctor)

@app.route('/book/<int:doctor_id>', methods=['GET', 'POST'])
@login_required
def book_appointment(doctor_id):
    """
    Handles the appointment booking process. 
    GET: Calculates available time slots based on doctor availability settings and existing bookings.
    POST: Validates the selected slot and creates the appointment record.
    """
    if session.get('role') == 'doctor':
        flash("Doctors cannot book appointments for themselves.", "warning")
        return redirect(url_for('doctor_dashboard'))

    doctor = db.get_or_404(Doctor, doctor_id)
    if doctor.is_blacklisted:
        flash('This doctor is no longer available for booking.', 'warning')
        return redirect(url_for('dashboard'))
    
    # --- Handle Booking Submission ---
    if request.method == 'POST':
        try:
            selected_slot = request.form.get('selected_slot')
            if not selected_slot:
                flash('Please select a valid time slot.', 'danger')
                return redirect(url_for('book_appointment', doctor_id=doctor_id))

            date_str, time_str = selected_slot.split('_')
            appt_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            appt_time = datetime.strptime(time_str, '%H:%M:%S').time()

            # 1. Validation: Check if Doctor is working at this time (Morning/Evening shift)
            avail_record = DoctorAvailability.query.filter_by(doctor_id=doctor.id, date=appt_date).first()
            is_doctor_working = False
            
            if avail_record:
                if appt_time.hour == 8 and avail_record.morning_available:
                    is_doctor_working = True
                elif appt_time.hour == 16 and avail_record.evening_available:
                    is_doctor_working = True
            
            if not is_doctor_working:
                flash('Doctor is not available at this time.', 'danger')
                return redirect(url_for('book_appointment', doctor_id=doctor_id))

            # 2. Validation: Check concurrency (Is slot already booked?)
            existing = Appointment.query.filter_by(
                doctor_id=doctor.id, 
                date=appt_date, 
                time=appt_time, 
                status='Booked').first()
            
            if existing:
                flash('This slot has just been booked. Please select another.', 'danger')
                return redirect(url_for('book_appointment', doctor_id=doctor_id))

            # 3. Create Appointment
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

    # --- Prepare Availability Grid for UI ---
    standard_slots = [time(8, 0), time(16, 0)] 
    today = date.today()
    date_range = [today + timedelta(days=d) for d in range(7)]
    
    # Fetch existing bookings to block out slots
    existing_appts = Appointment.query.filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date.in_(date_range),
        Appointment.status == 'Booked'
    ).all()
    booked_slots = set((appt.date, appt.time) for appt in existing_appts)
    
    # Fetch Doctor's Availability Settings (shifts)
    avail_settings = DoctorAvailability.query.filter(
        DoctorAvailability.doctor_id == doctor.id,
        DoctorAvailability.date.in_(date_range)
    ).all()
    avail_lookup = { a.date: a for a in avail_settings }

    availability_data = []
    
    # Build the data structure for the 7-day grid
    for day in date_range:
        day_settings = avail_lookup.get(day)
        slots_for_day = {'date': day, 'slots': []}
        
        for slot_time in standard_slots:
            is_booked = (day, slot_time) in booked_slots
            
            is_working = False
            if day_settings:
                if slot_time.hour == 8 and day_settings.morning_available:
                    is_working = True
                elif slot_time.hour == 16 and day_settings.evening_available:
                    is_working = True
            
            is_available = is_working and not is_booked
            
            slots_for_day['slots'].append({
                'time': slot_time, 
                'is_available': is_available 
            })
            
        availability_data.append(slots_for_day)
    
    return render_template('book_appointment.html', doctor=doctor, availability_data=availability_data)

@app.route('/appointment/cancel/<int:appt_id>', methods=['POST'])
@login_required
def cancel_appointment(appt_id):
    """
    Cancels an appointment. Validates that the requester is either the owning patient
    or the owning doctor.
    """
    appt = db.get_or_404(Appointment, appt_id)
    is_patient_owner = (session.get('role') == 'patient' and appt.patient_id == current_user.id)
    is_doctor_owner = (session.get('role') == 'doctor' and appt.doctor_id == current_user.id)

    if not (is_patient_owner or is_doctor_owner):
        flash('Permission denied.', 'danger')
        return redirect(url_for('home'))
        
    appt.status = 'Cancelled'
    db.session.commit()
    flash('Appointment has been cancelled.', 'success')
    if session.get('role') == 'doctor':
        return redirect(url_for('doctor_dashboard'))
    return redirect(url_for('dashboard'))

@app.route('/history')
@login_required
def patient_history():
    """
    Displays the patient's past appointments (Completed or Cancelled).
    """
    if session.get('role') != 'patient':
        return redirect(url_for('home'))

    past_appts = Appointment.query.filter(
        Appointment.patient_id == current_user.id,
        Appointment.status.in_(['Completed', 'Cancelled'])
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all() 
    
    return render_template('patient_history.html', appointments=past_appts)

# ---------------------------------------------------------------------------
# Doctor Dashboard & Management Routes
# ---------------------------------------------------------------------------

@app.route('/doctor/dashboard')
@login_required
def doctor_dashboard():
    """
    Main doctor dashboard. Shows upcoming schedule and a list of unique patients
    previously treated.
    """
    if session.get('role') != 'doctor':
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    # Get upcoming appointments
    upcoming_appts = Appointment.query.filter(
        Appointment.doctor_id == current_user.id,
        Appointment.date >= date.today(),
        Appointment.status == 'Booked' 
    ).order_by(Appointment.date, Appointment.time).all()

    # Get list of previously assigned patients
    completed_appts = Appointment.query.filter_by(
        doctor_id=current_user.id,
        status='Completed'
    ).order_by(Appointment.date.desc()).all()

    assigned_patients = []
    seen_patient_ids = set()
    for appt in completed_appts:
        if appt.patient_id not in seen_patient_ids:
            assigned_patients.append(appt.patient)
            seen_patient_ids.add(appt.patient_id)

    return render_template('doctor_dashboard.html', 
                           doctor=current_user, 
                           appointments=upcoming_appts,
                           assigned_patients=assigned_patients)

@app.route('/doctor/patient/history/<int:patient_id>')
@login_required
def doctor_patient_history(patient_id):
    """
    Allows a doctor to view the treatment history of a specific patient.
    Restricted to records where this doctor was the provider.
    """
    if session.get('role') != 'doctor':
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))

    patient = db.get_or_404(Patient, patient_id)

    # Fetch completed appointments for this specific doctor and patient
    completed_history = Appointment.query.filter(
        Appointment.patient_id == patient.id,
        Appointment.doctor_id == current_user.id,
        Appointment.status == 'Completed'
    ).order_by(Appointment.date.desc(), Appointment.time.desc()).all()

    return render_template('doctor_patient_history.html', 
                           patient=patient, 
                           history=completed_history,
                           doctor_name=current_user.name)

@app.route('/appointment/complete/<int:appt_id>', methods=['POST'])
@login_required
def mark_complete(appt_id):
    """
    Quick action to mark an appointment as 'Completed' without adding details.
    """
    if session.get('role') != 'doctor':
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
        
    appt = db.get_or_404(Appointment, appt_id)
    
    if appt.doctor_id != current_user.id:
        flash('You cannot manage appointments that are not yours.', 'danger')
        return redirect(url_for('doctor_dashboard'))
        
    appt.status = 'Completed'
    db.session.commit()
    flash(f'Appointment with {appt.patient.name} marked as complete.', 'success')
    return redirect(url_for('doctor_dashboard'))

@app.route('/appointment/update/<int:appt_id>', methods=['GET', 'POST'])
@login_required
def update_treatment(appt_id):
    """
    Interface for doctors to add treatment details, diagnosis, and prescriptions.
    Automatically marks the appointment as 'Completed' upon saving.
    """
    if session.get('role') != 'doctor':
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
        
    appt = db.get_or_404(Appointment, appt_id)
    
    if appt.doctor_id != current_user.id:
        flash('You cannot edit this appointment.', 'danger')
        return redirect(url_for('doctor_dashboard'))

    treatment = appt.treatment
    
    if request.method == 'POST':
        visit_type = request.form.get('visit_type')
        test_done = request.form.get('test_done')
        diagnosis = request.form.get('diagnosis')
        prescription = request.form.get('prescription')
        medicines_json = request.form.get('medicines_data') 
        
        if not treatment:
            treatment = Treatment(appointment_id=appt.id)
            db.session.add(treatment)
        
        treatment.visit_type = visit_type
        treatment.test_done = test_done
        treatment.diagnosis = diagnosis
        treatment.prescription = prescription
        treatment.medicines = medicines_json
        
        if appt.status == 'Booked':
            appt.status = 'Completed'

        db.session.commit()
        flash('Patient history updated successfully!', 'success')
        return redirect(url_for('doctor_dashboard'))

    return render_template('update_treatment.html', appointment=appt, treatment=treatment)

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """
    Allows patients to edit their personal profile information.
    Handles unique email constraints manually and passes errors via session/flash.
    """
    if session.get('role') != 'patient':
        flash('Doctors should contact admin to edit their profiles.', 'warning')
        return redirect(url_for('doctor_dashboard'))

    # Retrieve error message if it exists from a previous failed POST
    email_error_message = session.pop('email_error', None)

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        age_str = request.form.get('age')
        gender = request.form.get('gender')

        # Check if email is already taken by ANOTHER patient
        existing_email = Patient.query.filter_by(email=email).first()
        if existing_email and existing_email.id != current_user.id:
            session['email_error'] = 'This email address is already registered to another account.'
            return redirect(url_for('edit_profile'))

        current_user.name = name
        current_user.email = email
        current_user.age = int(age_str) if age_str else None
        current_user.gender = gender

        try:
            db.session.commit()
            flash('Your profile has been updated successfully!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred while updating profile: {e}', 'danger')

    return render_template('edit_profile.html', email_error_message=email_error_message)

@app.route('/doctor/availability', methods=['GET', 'POST'])
@login_required
def provide_availability():
    """
    Allows doctors to set their availability (Morning/Evening shifts) for the next 7 days.
    """
    if session.get('role') != 'doctor':
        flash('Access denied.', 'danger')
        return redirect(url_for('home'))
    
    today = date.today()
    next_7_days = [today + timedelta(days=i) for i in range(7)]

    if request.method == 'POST':
        try:
            for day in next_7_days:
                day_str = day.strftime('%Y-%m-%d')
                
                morning_status = request.form.get(f'morning_{day_str}') == 'on'
                evening_status = request.form.get(f'evening_{day_str}') == 'on'
                
                avail_record = DoctorAvailability.query.filter_by(
                    doctor_id=current_user.id, date=day
                ).first()
                
                if not avail_record:
                    avail_record = DoctorAvailability(
                        doctor_id=current_user.id,
                        date=day
                    )
                    db.session.add(avail_record)
                
                avail_record.morning_available = morning_status
                avail_record.evening_available = evening_status
            
            db.session.commit()
            flash('Availability schedule updated successfully.', 'success')
            return redirect(url_for('doctor_dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating availability: {e}', 'danger')

    # Fetch existing availability to pre-fill the form
    existing_availability = DoctorAvailability.query.filter(
        DoctorAvailability.doctor_id == current_user.id,
        DoctorAvailability.date.in_(next_7_days)
    ).all()
    
    availability_map = { record.date: record for record in existing_availability }
    
    display_data = []
    for day in next_7_days:
        record = availability_map.get(day)
        display_data.append({
            'date_obj': day,
            'formatted_date': day.strftime('%d/%m/%Y'),
            'iso_date': day.strftime('%Y-%m-%d'),
            'morning': record.morning_available if record else False,
            'evening': record.evening_available if record else False
        })

    return render_template('doctor_availability.html', availability_data=display_data)

# ---------------------------------------------------------------------------
# Admin Routes
# ---------------------------------------------------------------------------

@app.route('/admin-434345ndfsdj') 
def admin_dashboard():
    """
    Administrative dashboard. Includes search functionality for doctors and patients,
    and lists all upcoming system appointments.
    """
    search_query = request.args.get('q', '').strip()
    
    if search_query:
        search_pattern = f"%{search_query}%"
        
        # Search Doctors by Name OR Email
        doctors = Doctor.query.filter(
            (Doctor.name.like(search_pattern)) | 
            (Doctor.email.like(search_pattern))
        ).order_by(Doctor.name).all()
        
        # Search Patients by Name OR Email
        patients = Patient.query.filter(
            (Patient.name.like(search_pattern)) | 
            (Patient.email.like(search_pattern))
        ).order_by(Patient.name).all()
    else:
        # Default: Show all
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
    """
    Admin route to register a new doctor, including bio and initial password.
    """
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        specialization = request.form.get('specialization')
        department_id = request.form.get('department_id')
        experience_str = request.form.get('experience')
        password = request.form.get('password') 
        bio = request.form.get('bio')

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
            experience=experience,
            bio=bio
        )
        new_doctor.set_password(password if password else '123') 
        
        db.session.add(new_doctor)
        db.session.commit()
        flash(f'Dr. {new_doctor.name} has been added successfully.', 'success')
        return redirect(url_for('admin_dashboard'))

    departments = Department.query.all()
    return render_template('add_doctor.html', departments=departments)

@app.route('/admin/doctor/edit/<int:doctor_id>', methods=['GET', 'POST'])
def admin_edit_doctor(doctor_id):
    """
    Admin route to update doctor details.
    """
    doctor = db.get_or_404(Doctor, doctor_id)
    departments = Department.query.all()

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        specialization = request.form.get('specialization')
        department_id = request.form.get('department_id')
        experience_str = request.form.get('experience')
        bio = request.form.get('bio')

        existing_email_user = Doctor.query.filter_by(email=email).first()
        if existing_email_user and existing_email_user.id != doctor.id:
            flash('This email is already in use by another doctor.', 'danger')
            return render_template('edit_doctor.html', doctor=doctor, departments=departments)

        doctor.name = name
        doctor.email = email
        doctor.specialization = specialization
        doctor.department_id = int(department_id)
        doctor.experience = int(experience_str) if experience_str else None
        doctor.bio = bio

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
    """
    Admin route to update patient details.
    """
    patient = db.get_or_404(Patient, patient_id)

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
    """
    Admin route to delete a patient and their associated history.
    """
    patient = db.get_or_404(Patient, patient_id)
    Appointment.query.filter_by(patient_id=patient.id).delete()
    db.session.delete(patient)
    db.session.commit()
    flash(f'Patient {patient.name} and their history have been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/doctor/delete/<int:doctor_id>', methods=['POST'])
def admin_delete_doctor(doctor_id):
    """
    Admin route to delete a doctor and their associated appointments.
    """
    doctor = db.get_or_404(Doctor, doctor_id)
    Appointment.query.filter_by(doctor_id=doctor.id).delete()
    db.session.delete(doctor)
    db.session.commit()
    flash(f'Dr. {doctor.name} and their appointments have been deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/doctor/blacklist/<int:doctor_id>', methods=['POST'])
def admin_blacklist_doctor(doctor_id):
    """
    Suspends a doctor's account.
    """
    doctor = db.get_or_404(Doctor, doctor_id)
    doctor.is_blacklisted = True
    db.session.commit()
    flash(f'Dr. {doctor.name} has been blacklisted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/doctor/whitelist/<int:doctor_id>', methods=['POST'])
def admin_whitelist_doctor(doctor_id):
    """
    Restores a suspended doctor's account.
    """
    doctor = db.get_or_404(Doctor, doctor_id)
    doctor.is_blacklisted = False
    db.session.commit()
    flash(f'Dr. {doctor.name} has been restored.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/patient/blacklist/<int:patient_id>', methods=['POST'])
def admin_blacklist_patient(patient_id):
    """
    Suspends a patient's account.
    """
    patient = db.get_or_404(Patient, patient_id)
    patient.is_blacklisted = True
    db.session.commit()
    flash(f'Patient {patient.name} has been blacklisted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/patient/whitelist/<int:patient_id>', methods=['POST'])
def admin_whitelist_patient(patient_id):
    """
    Restores a suspended patient's account.
    """
    patient = db.get_or_404(Patient, patient_id)
    patient.is_blacklisted = False
    db.session.commit()
    flash(f'Patient {patient.name} has been restored.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/patient/history/view/<int:patient_id>')
def admin_patient_history_view(patient_id):
    """
    Admin view to see all history for a specific patient.
    """
    patient = db.get_or_404(Patient, patient_id)
    history = Appointment.query.filter(
        Appointment.patient_id == patient.id
    ).order_by(Appointment.date.desc()).all()
    return render_template('admin_patient_history.html', patient=patient, history=history)

# ---------------------------------------------------------------------------
# Application Entry Point & Demo Data
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Initialize demo data if the database is empty
        if not Department.query.first():
            print("Initializing demo data...")
            dept1 = Department(name='Cardiology', description='Heart issues.')
            dept2 = Department(name='Oncology', description='Cancer treatment.')
            dept3 = Department(name='General', description='General health.')
            db.session.add_all([dept1, dept2, dept3])
            db.session.commit()

            doc1 = Doctor(name='Dr. Abcde', email='abcde@hospital.com', specialization='Cardiologist', department=dept1, experience=10, bio="Expert in heart surgeries.")
            doc1.set_password('doctor123')
            
            doc2 = Doctor(name='Dr. Pqrst', email='pqrst@hospital.com', specialization='Cardiologist', department=dept1, experience=5, bio="Specialist in preventive cardiology.")
            doc2.set_password('doctor123')

            doc3 = Doctor(name='Dr. Mnop', email='mnop@hospital.com', specialization='Medical Oncologist', department=dept2, experience=8, bio="Focuses on immunotherapy.")
            doc3.set_password('doctor123')

            db.session.add_all([doc1, doc2, doc3])
            
            demo_patient = Patient(name='John Doe', email='john@test.com', age=30, gender='Male')
            demo_patient.set_password('123')
            db.session.add(demo_patient)
            db.session.commit()
            
            appt1 = Appointment(patient=demo_patient, doctor=doc3, date=date(2025, 9, 24), time=time(8, 12), status='Booked')
            db.session.add(appt1)
            db.session.commit()
            print("Demo data initialized successfully.")

    app.run(debug=True)