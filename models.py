from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# Department (No changes)
class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    doctors = db.relationship('Doctor', backref='department', lazy=True)

    def __repr__(self):
        return f"<Department {self.name}>"

# Doctor (MODIFIED)
class Doctor(db.Model):
    __tablename__ = 'doctors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    specialization = db.Column(db.String(120))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    # --- Field for blacklisting ---
    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)
    
    # --- Field for 'Add Doctor' form ---
    experience = db.Column(db.Integer, nullable=True) 
    
    appointments = db.relationship('Appointment', backref='doctor', lazy=True)

    def __repr__(self):
        return f"<Doctor {self.name} ({self.specialization})>"

# Patient (MODIFIED)
class Patient(db.Model, UserMixin): 
    __tablename__ = 'patients'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    
    password_hash = db.Column(db.String(200), nullable=False)
    
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))

    # --- Field for blacklisting ---
    is_blacklisted = db.Column(db.Boolean, default=False, nullable=False)

    appointments = db.relationship('Appointment', backref='patient', lazy=True)

    # --- PASSWORD METHODS ---
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Patient {self.name}>"

# Appointment (No changes)
class Appointment(db.Model):
    __tablename__ = 'appointments'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(50), nullable=False, default='Booked') # e.g., 'Booked', 'Cancelled', 'Completed'
    treatment = db.relationship('Treatment', backref='appointment', uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Appointment {self.id} - {self.status}>"

# Treatment (No changes)
class Treatment(db.Model):
    __tablename__ = 'treatments'
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id'), nullable=False)
    diagnosis = db.Column(db.Text, nullable=False)
    prescription = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Treatment for Appointment {self.appointment_id}>"