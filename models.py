from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()

# Department
class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    doctors = db.relationship('Doctor', backref='department', lazy=True)

# Doctor
class Doctor(db.Model, UserMixin):
    __tablename__ = 'doctors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    specialization = db.Column(db.String(120))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    # --- NEW FIELD ---
    bio = db.Column(db.Text, nullable=True) 
    # -----------------

    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)
    experience = db.Column(db.Integer, nullable=True) 
    password_hash = db.Column(db.String(200), nullable=False, default='pbkdf2:sha256:dummy') 

    appointments = db.relationship('Appointment', backref='doctor', lazy=True)
    availability = db.relationship('DoctorAvailability', backref='doctor', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Doctor Availability
class DoctorAvailability(db.Model):
    __tablename__ = 'doctor_availability'
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    morning_available = db.Column(db.Boolean, default=False) # 08:00 - 12:00
    evening_available = db.Column(db.Boolean, default=False) # 16:00 - 21:00

# Patient
class Patient(db.Model, UserMixin): 
    __tablename__ = 'patients'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)

    appointments = db.relationship('Appointment', backref='patient', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Appointment
class Appointment(db.Model):
    __tablename__ = 'appointments'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(50), nullable=False, default='Booked') 
    treatment = db.relationship('Treatment', backref='appointment', uselist=False, cascade="all, delete-orphan")

# Treatment
class Treatment(db.Model):
    __tablename__ = 'treatments'
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id'), nullable=False)
    visit_type = db.Column(db.String(100), nullable=True)
    test_done = db.Column(db.String(200), nullable=True)
    diagnosis = db.Column(db.Text, nullable=True)
    prescription = db.Column(db.Text, nullable=True) 
    medicines = db.Column(db.Text, nullable=True) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_medicines_list(self):
        if self.medicines:
            try:
                return json.loads(self.medicines)
            except:
                return []
        return []