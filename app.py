import os
from datetime import datetime, timedelta
import jwt
import random
from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from dotenv import load_dotenv
import uuid

# Load .env variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# -----------------------
# HOME ROUTE (Fixes 404)
# -----------------------
@app.route("/")
def home():
    return jsonify({"status": "StuFlow Backend Running"}), 200


# -----------------------
# CONFIGURATION
# -----------------------

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # Convert postgres:// → postgresql+psycopg:// (required for psycopg3)
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    # Local MySQL for development
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"mysql+mysqlconnector://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@"
        f"{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
    )


app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email config
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@stuflow.com')

db = SQLAlchemy(app)
mail = Mail(app)


# -----------------------
# MODELS
# -----------------------

class VerificationCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(6), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    def is_valid(self):
        return datetime.utcnow() < self.expires_at and not self.used


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(10), nullable=False, default="student")

    tasks = db.relationship('Task', backref='user', lazy=True)
    events = db.relationship('Event', backref='user', lazy=True)
    flashcards = db.relationship('Flashcard', backref='user', lazy=True)
    eco_logs = db.relationship('EcoLog', backref='user', lazy=True)
    classes = db.relationship('Class', backref='teacher', lazy=True)
    announcements = db.relationship('Announcement', backref='teacher', lazy=True)
    resources = db.relationship('ResourceFile', backref='teacher', foreign_keys='ResourceFile.teacher_id', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(50), nullable=False, default="Ongoing")


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    date = db.Column(db.Date, nullable=False)
    type = db.Column(db.String(20), nullable=False)


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    submitted_file = db.Column(db.String(255))
    status = db.Column(db.String(20), default="Submitted")
    date_submitted = db.Column(db.DateTime, default=datetime.utcnow)
    grade = db.Column(db.Integer)
    teacher_comment = db.Column(db.Text)

    task = db.relationship('Task', backref='submissions', lazy=True)
    student = db.relationship('User', foreign_keys=[student_id], lazy=True)


class Flashcard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    front = db.Column(db.Text, nullable=False)
    back = db.Column(db.Text, nullable=False)


class ResourceFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    class_name = db.Column(db.String(100), default="All Classes")
    date_uploaded = db.Column(db.DateTime, default=datetime.utcnow)


class EcoLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    waste_count = db.Column(db.Integer, default=0)
    energy_count = db.Column(db.Integer, default=0)
    transport_count = db.Column(db.Integer, default=0)
    score = db.Column(db.Integer, default=0)

    __table_args__ = (db.UniqueConstraint('user_id', 'date', name='_user_date_uc'),)


class Class(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    estimated_students = db.Column(db.Integer, default=0)


class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    recipient = db.Column(db.String(100), nullable=False)
    date_posted = db.Column(db.DateTime, default=datetime.utcnow)


# -----------------------
# DECORATORS
# -----------------------

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if "Authorization" in request.headers:
            token = request.headers["Authorization"].split(" ")[1]

        if not token:
            return jsonify({"message": "Token missing"}), 401

        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            user = User.query.get(data["user_id"])

            if not user:
                return jsonify({"message": "Invalid token"}), 401

            g.current_user = user

        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token expired"}), 401
        except Exception:
            return jsonify({"message": "Invalid token"}), 401

        return f(*args, **kwargs)

    return decorated


def role_required(role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            allowed_roles = role if isinstance(role, list) else [role]
            if g.current_user.role not in allowed_roles:
                return jsonify({"message": "Forbidden"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# -----------------------
# AUTH ENDPOINTS
# -----------------------

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    role = data.get('role', 'student')

    if User.query.filter_by(email=email).first():
        return jsonify({"message": "Account already exists"}), 409

    new_user = User(name=name, email=email, role=role)
    new_user.set_password(password)

    try:
        db.session.add(new_user)
        db.session.commit()

        token = jwt.encode({
            "user_id": new_user.id,
            "exp": datetime.utcnow() + timedelta(hours=24)
        }, app.config['SECRET_KEY'], algorithm="HS256")

        return jsonify({"message": "Account created", "token": token}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error: {e}"}), 500


@app.route('/api/login', methods=['POST'])
def login():
    auth = request.get_json()
    email = auth.get('email')
    password = auth.get('password')

    user = User.query.filter_by(email=email).first()

    if not user or not user.check_password(password):
        return jsonify({"message": "Invalid credentials"}), 401

    # generate verification code
    code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    VerificationCode.query.filter_by(email=email).update({"used": True})

    ver = VerificationCode(email=email, code=code, expires_at=expires_at)
    db.session.add(ver)
    db.session.commit()

    # send email
    try:
        msg = Message(
            subject="StuFlow Verification Code",
            recipients=[email],
            body=f"Your verification code is: {code}\n\nExpires in 10 minutes."
        )
        mail.send(msg)
    except Exception:
        return jsonify({"message": "Email failed"}), 500

    return jsonify({"message": "Verification code sent", "requires_verification": True}), 200


@app.route('/api/verify', methods=['POST'])
def verify_code():
    data = request.get_json()
    email = data.get('email')
    code = data.get('code')

    ver = VerificationCode.query.filter_by(email=email, code=code, used=False).first()

    if not ver or not ver.is_valid():
        return jsonify({"message": "Invalid or expired code"}), 401

    ver.used = True
    user = User.query.filter_by(email=email).first()

    token = jwt.encode({
        "user_id": user.id,
        "exp": datetime.utcnow() + timedelta(hours=24)
    }, app.config['SECRET_KEY'], algorithm="HS256")

    db.session.commit()

    return jsonify({"message": "Verified", "token": token, "role": user.role, "name": user.name})


@app.route('/api/verify/resend', methods=['POST'])
def resend_code():
    data = request.get_json()
    email = data.get('email')

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"message": "User not found"}), 404

    code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    VerificationCode.query.filter_by(email=email).update({"used": True})

    ver = VerificationCode(email=email, code=code, expires_at=expires_at)
    db.session.add(ver)
    db.session.commit()

    try:
        msg = Message(
            subject="StuFlow New Verification Code",
            recipients=[email],
            body=f"Your new verification code is: {code}"
        )
        mail.send(msg)
    except Exception:
        return jsonify({"message": "Email failed"}), 500

    return jsonify({"message": "New code sent"}), 200


# -----------------------
# USER ENDPOINTS
# -----------------------

@app.route('/api/user/me', methods=['GET'])
@token_required
def get_current_user():
    u = g.current_user
    return jsonify({
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role
    })


@app.route('/api/user/profile', methods=['PUT'])
@token_required
def update_profile():
    data = request.get_json()
    new_name = data.get('name')

    if not new_name:
        return jsonify({"message": "Name required"}), 400

    g.current_user.name = new_name

    try:
        db.session.commit()
        return jsonify({"message": "Profile updated", "name": new_name})
    except:
        db.session.rollback()
        return jsonify({"message": "Update failed"}), 500


@app.route('/api/user/password', methods=['PUT'])
@token_required
def update_password():
    data = request.get_json()
    old = data.get('old_password')
    new = data.get('new_password')

    if not old or not new:
        return jsonify({"message": "Missing fields"}), 400

    if len(new) < 6:
        return jsonify({"message": "Password too short"}), 400

    if not g.current_user.check_password(old):
        return jsonify({"message": "Invalid old password"}), 401

    g.current_user.set_password(new)

    try:
        db.session.commit()
        return jsonify({"message": "Password updated"})
    except:
        db.session.rollback()
        return jsonify({"message": "Update failed"}), 500


# -----------------------
# TASK ENDPOINTS
# -----------------------

@app.route('/api/tasks', methods=['GET'])
@token_required
def get_tasks():
    out = []

    if g.current_user.role == 'teacher':
        tasks = Task.query.filter_by(user_id=g.current_user.id, status='Assignment').all()
        for t in tasks:
            out.append({
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "due": t.due_date.strftime('%Y-%m-%d'),
                "status": t.status
            })
    else:
        data = db.session.query(Task, Submission.teacher_comment) \
            .outerjoin(Submission, Submission.task_id == Task.id) \
            .filter(Task.user_id == g.current_user.id).all()

        for t, comment in data:
            out.append({
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "due": t.due_date.strftime('%Y-%m-%d'),
                "status": t.status,
                "teacher_comment": comment
            })

    return jsonify(out)


@app.route('/api/tasks', methods=['POST'])
@token_required
@role_required('teacher')
def create_task():
    data = request.get_json()

    if not data.get('title') or not data.get('due'):
        return jsonify({"message": "Missing fields"}), 400

    teacher_task = Task(
        user_id=g.current_user.id,
        title=data['title'],
        description=data.get('description', ''),
        due_date=datetime.strptime(data['due'], '%Y-%m-%d').date(),
        status='Assignment'
    )

    db.session.add(teacher_task)
    db.session.flush()

    students = User.query.filter_by(role='student').all()
    for s in students:
        st = Task(
            user_id=s.id,
            title=data['title'],
            description=data.get('description', ''),
            due_date=teacher_task.due_date,
            status='Ongoing'
        )
        db.session.add(st)

    db.session.commit()

    return jsonify({"message": "Assignment created", "id": teacher_task.id}), 201


@app.route('/api/tasks/<int:task_id>/complete', methods=['PUT'])
@token_required
def complete_task(task_id):
    task = Task.query.filter_by(id=task_id, user_id=g.current_user.id).first()

    if not task:
        return jsonify({"message": "Task not found"}), 404

    task.status = "Completed"
    db.session.commit()

    return jsonify({"message": "Task completed"})


# -----------------------
# SUBMISSION ENDPOINTS
# -----------------------

@app.route('/api/submissions/<int:task_id>/submit', methods=['POST'])
@token_required
@role_required('student')
def submit_task(task_id):
    task = Task.query.filter_by(id=task_id, user_id=g.current_user.id).first()

    if not task:
        return jsonify({"message": "Task not found"}), 404

    if task.status != "Ongoing":
        return jsonify({"message": "Task already submitted"}), 400

    if 'submission_file' not in request.files:
        return jsonify({"message": "No file"}), 400

    file = request.files['submission_file']

    if file.filename == '':
        return jsonify({"message": "Empty filename"}), 400

    filename = secure_filename(file.filename)

    task.status = "Completed"

    sub = Submission(
        task_id=task_id,
        student_id=g.current_user.id,
        submitted_file=filename
    )

    db.session.add(sub)
    db.session.commit()

    return jsonify({"message": f"Submitted {filename}"})


@app.route('/api/submissions', methods=['GET'])
@token_required
@role_required('teacher')
def get_submissions():
    tasks = Task.query.filter(Task.status != 'Assignment').all()
    ids = [t.id for t in tasks]

    subs = Submission.query.filter(Submission.task_id.in_(ids)) \
        .order_by(Submission.date_submitted.desc()).all()

    out = []
    for s in subs:
        t = Task.query.get(s.task_id)
        u = User.query.get(s.student_id)

        out.append({
            "id": s.id,
            "task_id": s.task_id,
            "student_name": u.name,
            "assignment_title": t.title,
            "due_date": t.due_date.strftime('%Y-%m-%d'),
            "submitted_file": s.submitted_file,
            "status": s.status,
            "grade": s.grade,
            "teacher_comment": s.teacher_comment
        })

    return jsonify(out)


@app.route('/api/submissions/<int:submission_id>/grade', methods=['PUT'])
@token_required
@role_required('teacher')
def grade_submission(submission_id):
    data = request.get_json()
    grade = data.get('grade')
    comment = data.get('teacher_comment')

    if grade is None or not (0 <= grade <= 100):
        return jsonify({"message": "Invalid grade"}), 400

    sub = Submission.query.get(submission_id)
    if not sub:
        return jsonify({"message": "Not found"}), 404

    sub.grade = grade
    sub.status = "Graded"
    sub.teacher_comment = comment

    task = Task.query.get(sub.task_id)
    task.status = f"Graded: {grade}%"

    try:
        db.session.commit()
        return jsonify({"message": "Graded"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error: {e}"}), 500


# -----------------------
# EVENT ENDPOINTS
# -----------------------

@app.route('/api/events', methods=['GET'])
@token_required
def get_events():
    events = Event.query.filter_by(user_id=g.current_user.id).all()
    out = []
    for e in events:
        out.append({
            "id": e.id,
            "title": e.title,
            "date": e.date.strftime('%Y-%m-%d'),
            "type": e.type
        })
    return jsonify(out)


@app.route('/api/events', methods=['POST'])
@token_required
def create_event():
    data = request.get_json()

    if not data.get('title') or not data.get('date') or not data.get('type'):
        return jsonify({"message": "Missing fields"}), 400

    ev = Event(
        user_id=g.current_user.id,
        title=data['title'],
        date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
        type=data['type']
    )
    db.session.add(ev)
    db.session.commit()

    return jsonify({"message": "Event created", "id": ev.id}), 201


# -----------------------
# FLASHCARDS
# -----------------------

@app.route('/api/flashcards', methods=['GET'])
@token_required
def get_flashcards():
    fs = Flashcard.query.filter_by(user_id=g.current_user.id).all()
    return jsonify([{"id": f.id, "front": f.front, "back": f.back} for f in fs])


@app.route('/api/flashcards', methods=['POST'])
@token_required
def create_flashcard():
    data = request.get_json()

    if not data.get('front') or not data.get('back'):
        return jsonify({"message": "Missing fields"}), 400

    card = Flashcard(
        user_id=g.current_user.id,
        front=data['front'],
        back=data['back']
    )
    db.session.add(card)
    db.session.commit()

    return jsonify({"message": "Flashcard created", "id": card.id}), 201


# -----------------------
# RESOURCES
# -----------------------

@app.route('/api/resources/upload', methods=['POST'])
@token_required
@role_required('teacher')
def upload_resource():
    if 'resource_file' not in request.files:
        return jsonify({"message": "No file"}), 400

    file = request.files['resource_file']
    class_name = request.form.get('class_name', 'All Classes')

    if file.filename == "":
        return jsonify({"message": "Empty filename"}), 400

    filename = secure_filename(file.filename)

    res = ResourceFile(
        teacher_id=g.current_user.id,
        file_name=filename,
        file_path=f"mock_storage/{g.current_user.id}/{filename}",  # storage system stub
        class_name=class_name
    )

    db.session.add(res)
    db.session.commit()

    return jsonify({"message": "Uploaded", "id": res.id}), 201


@app.route('/api/resources', methods=['GET'])
@token_required
def get_resources():
    if g.current_user.role == 'teacher':
        resources = ResourceFile.query.filter_by(teacher_id=g.current_user.id) \
            .order_by(ResourceFile.date_uploaded.desc()).all()
    else:
        resources = ResourceFile.query.filter_by(class_name='All Classes') \
            .order_by(ResourceFile.date_uploaded.desc()).all()

    out = []
    for r in resources:
        teacher = User.query.get(r.teacher_id)
        out.append({
            "id": r.id,
            "file_name": r.file_name,
            "class_name": r.class_name,
            "teacher_name": teacher.name if teacher else "Unknown",
            "date_uploaded": r.date_uploaded.strftime('%Y-%m-%d')
        })

    return jsonify(out)


# -----------------------
# ECO LOG ENDPOINTS
# -----------------------

@app.route('/api/eco-log/action/<string:action>', methods=['POST'])
@token_required
def log_action(action):
    if action not in ['waste', 'energy', 'transport']:
        return jsonify({"message": "Invalid action"}), 400

    today = datetime.utcnow().date()
    log = EcoLog.query.filter_by(user_id=g.current_user.id, date=today).first()

    if not log:
        log = EcoLog(user_id=g.current_user.id, date=today, waste_count=0, energy_count=0, transport_count=0, score=0)
        db.session.add(log)

    if action == 'waste':
        log.waste_count += 1
        log.score += 5
    elif action == 'energy':
        log.energy_count += 1
        log.score += 5
    elif action == 'transport':
        log.transport_count += 1
        log.score += 10

    db.session.commit()

    return jsonify({
        "waste": log.waste_count,
        "energy": log.energy_count,
        "transport": log.transport_count,
        "score": log.score
    })


@app.route('/api/eco-log/daily', methods=['GET'])
@token_required
def get_log():
    date_str = request.args.get('date', datetime.utcnow().strftime('%Y-%m-%d'))

    try:
        day = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        return jsonify({"message": "Invalid date"}), 400

    log = EcoLog.query.filter_by(user_id=g.current_user.id, date=day).first()

    if not log:
        return jsonify({"waste": 0, "energy": 0, "transport": 0, "score": 0})

    return jsonify({
        "waste": log.waste_count,
        "energy": log.energy_count,
        "transport": log.transport_count,
        "score": log.score
    })


# -----------------------
# CLASS ENDPOINTS
# -----------------------

@app.route('/api/classes', methods=['GET'])
@token_required
@role_required('teacher')
def get_classes():
    classes = Class.query.filter_by(teacher_id=g.current_user.id).all()
    return jsonify([
        {"id": c.id, "name": c.name, "estimated_students": c.estimated_students}
        for c in classes
    ])


@app.route('/api/classes', methods=['POST'])
@token_required
@role_required('teacher')
def create_class():
    data = request.get_json()

    if not data.get('name'):
        return jsonify({"message": "Missing name"}), 400

    cid = f"class-{uuid.uuid4().hex[:8]}"

    cls = Class(
        id=cid,
        teacher_id=g.current_user.id,
        name=data['name'],
        estimated_students=data.get('size', 30)
    )

    db.session.add(cls)
    db.session.commit()

    return jsonify({"message": "Created", "id": cid}), 201


# -----------------------
# ANNOUNCEMENTS
# -----------------------

@app.route('/api/announcements', methods=['POST'])
@token_required
@role_required('teacher')
def create_announcement():
    data = request.get_json()

    if not data.get('title') or not data.get('message') or not data.get('recipient'):
        return jsonify({"message": "Missing fields"}), 400

    ann = Announcement(
        teacher_id=g.current_user.id,
        title=data['title'],
        message=data['message'],
        recipient=data['recipient'],
        date_posted=datetime.utcnow()
    )

    db.session.add(ann)
    db.session.commit()

    return jsonify({"message": "Announcement posted"}), 201


@app.route('/api/announcements', methods=['GET'])
@token_required
def get_announcements():
    if g.current_user.role == "student":
        anns = Announcement.query.order_by(Announcement.date_posted.desc()).all()
    else:
        anns = Announcement.query.filter_by(teacher_id=g.current_user.id) \
            .order_by(Announcement.date_posted.desc()).all()

    return jsonify([
        {
            "id": a.id,
            "title": a.title,
            "message": a.message,
            "recipient": a.recipient,
            "date": a.date_posted.strftime('%Y-%m-%d')
        }
        for a in anns
    ])


# -----------------------
# DB INIT
# -----------------------

@app.cli.command("init-db")
def init_db():
    try:
        with app.app_context():
            db.drop_all()
            db.create_all()

            teacher = User(
                name="Alex Johnson (Teacher)",
                email="teacher@stuflow.com",
                role="teacher"
            )
            teacher.set_password("password")

            student = User(
                name="Sam Smith (Student)",
                email="student@stuflow.com",
                role="student"
            )
            student.set_password("password")

            db.session.add(teacher)
            db.session.add(student)
            db.session.commit()

        print("Database initialized.")

    except Exception as e:
        print("Error:", e)


# -----------------------
# RUN APP
# -----------------------

if __name__ == '__main__':
    app.run(debug=True)
