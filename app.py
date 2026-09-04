from __future__ import annotations

import os
import secrets
import json
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from collections import defaultdict

app = Flask(__name__)
app.secret_key = "gurukul-next-secret-key"
socketio = SocketIO(app, cors_allowed_origins="*")
room_members = defaultdict(dict)
room_hosts = {}
otp_sessions: Dict[str, Dict[str, Any]] = {}
api_tokens: Dict[str, Dict[str, Any]] = {}
api_attempts: Dict[str, Dict[str, Any]] = {}
live_sessions: Dict[str, Dict[str, Any]] = {}
room_tokens: Dict[str, Dict[str, Any]] = {}


@dataclass
class Lesson:
    title: str
    duration: str
    notes: str
    audio_summary: str


@dataclass
class Question:
    prompt: str
    options: List[str]
    answer: str
    explanation: str
    topic: str


@dataclass
class Course:
    course_id: str
    title: str
    category: str
    level: str
    price: str
    description: str
    tenant_id: Optional[str] = None
    created_by: Optional[str] = None
    lessons: List[Lesson] = field(default_factory=list)
    quiz_bank: List[Question] = field(default_factory=list)


@dataclass
class User:
    user_id: str
    name: str
    email: str
    password: str
    role: str
    phone: str = ""
    device_tokens: List[str] = field(default_factory=list)
    tenant_id: Optional[str] = None
    online: bool = False
    approved: bool = True
    course_ids: List[str] = field(default_factory=list)


@dataclass
class Tenant:
    tenant_id: str
    company_name: str
    tenant_type: str
    workflow: Dict[str, Any]
    admins: List[str] = field(default_factory=list)
    instructors: List[str] = field(default_factory=list)
    students: List[str] = field(default_factory=list)
    meeting_provider: str = "Zoom"


@dataclass
class LiveClass:
    class_id: str
    title: str
    tenant_id: str
    instructor_id: str
    course_id: Optional[str]
    scheduled_at: str
    provider: str
    join_url: str = ""
    attendees: List[str] = field(default_factory=list)
    allowed_students: List[str] = field(default_factory=list)
    status: str = "scheduled"


@dataclass
class Attempt:
    attempt_id: str
    user_id: str
    course_id: str
    responses: Dict[str, str]
    score: int
    total_marks: int
    weakness_tags: List[str]
    time_taken: int
    submitted_at: str
    percentile: float


def api_response(data=None, message=None, success=True, status=200, **extra):
    payload = {"success": success}
    if message:
        payload["message"] = message
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return payload, status


def current_api_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token_data = api_tokens.get(header[7:])
    if not token_data or token_data["expires_at"] <= datetime.now(timezone.utc):
        return None
    return platform.users.get(token_data["user_id"])


def public_course(course: Course) -> Dict[str, Any]:
    price_digits = "".join(character for character in course.price if character.isdigit())
    return {
        "id": course.course_id,
        "title": course.title,
        "slug": course.course_id,
        "category": course.category,
        "pricing": {"amount": int(price_digits or 0), "currency": "NPR", "discount_percent": 0},
        "thumbnail_url": None,
        "rating": None,
        "total_students": 0,
    }


def parse_iso_datetime(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


class SuperAdmin:
    def __init__(self, name: str, email: str, password: str):
        self.user = User(
            user_id="sa-001",
            name=name,
            email=email,
            password=password,
            role="superadmin",
        )
        self.tenants: Dict[str, Tenant] = {}
        self.audit_log: List[str] = []

    def define_tenant_workflow(self, tenant: Tenant, workflow: Dict[str, Any]) -> None:
        tenant.workflow = workflow
        self.audit_log.append(f"Workflow defined for {tenant.company_name}: {workflow}")

    def create_tenant(self, company_name: str, tenant_type: str, meeting_provider: str = "Zoom") -> Tenant:
        tenant_id = f"tenant-{len(self.tenants) + 1}"
        tenant = Tenant(
            tenant_id=tenant_id,
            company_name=company_name,
            tenant_type=tenant_type,
            workflow={
                "enroll": True,
                "video_lessons": True,
                "quiz": True,
                "dashboard": True,
                "live_classes": True,
                "doubt_support": True,
            },
            meeting_provider=meeting_provider,
        )
        self.tenants[tenant_id] = tenant
        self.audit_log.append(f"Tenant created: {company_name} ({tenant_type})")
        return tenant

    def assign_admin(self, tenant: Tenant, user_id: str) -> None:
        tenant.admins.append(user_id)
        self.audit_log.append(f"Admin assigned to {tenant.company_name}: {user_id}")

    def assign_instructor(self, tenant: Tenant, user_id: str) -> None:
        tenant.instructors.append(user_id)
        self.audit_log.append(f"Instructor assigned to {tenant.company_name}: {user_id}")

    def assign_student(self, tenant: Tenant, user_id: str) -> None:
        tenant.students.append(user_id)
        self.audit_log.append(f"Student assigned to {tenant.company_name}: {user_id}")


class OnlineClassPlatform:
    def __init__(self):
        self.users: Dict[str, User] = {}
        self.tenants: Dict[str, Tenant] = {}
        self.courses: Dict[str, Course] = self._build_courses()
        self.live_classes: Dict[str, LiveClass] = {}
        self.attempts: Dict[str, Attempt] = {}
        self.superadmin = None

    def _build_courses(self) -> Dict[str, Course]:
        math_lesson_1 = Lesson(
            title="Algebra Basics",
            duration="18 min",
            notes="Learn variables, linear equations, and solving techniques.",
            audio_summary="Revision of key algebra rules and shortcut patterns.",
        )
        math_lesson_2 = Lesson(
            title="Quadratic Equations",
            duration="22 min",
            notes="Factorization, formula methods, and graph interpretation.",
            audio_summary="Quick memory drill for roots and discriminants.",
        )
        physics_lesson = Lesson(
            title="Kinematics",
            duration="25 min",
            notes="Motion, velocity, displacement, and graph-based problem solving.",
            audio_summary="Key formulas for distance, speed, and acceleration.",
        )

        math_questions = [
            Question(
                prompt="Solve: 3x + 7 = 19",
                options=["x = 2", "x = 3", "x = 4", "x = 5"],
                answer="x = 4",
                explanation="Subtract 7 from both sides: 3x = 12, then divide by 3.",
                topic="Algebra",
            ),
            Question(
                prompt="What is the value of x in x^2 - 5x + 6 = 0?",
                options=["1 and 6", "2 and 3", "-2 and -3", "-1 and -6"],
                answer="2 and 3",
                explanation="The equation factors to (x - 2)(x - 3) = 0.",
                topic="Quadratics",
            ),
        ]

        physics_questions = [
            Question(
                prompt="A car moves 20 m in 4 s. What is its average speed?",
                options=["4 m/s", "5 m/s", "6 m/s", "8 m/s"],
                answer="5 m/s",
                explanation="Average speed = total distance / total time = 20 / 4 = 5.",
                topic="Motion",
            ),
            Question(
                prompt="If an object accelerates from rest at 2 m/s^2 for 5 s, what is its velocity?",
                options=["5 m/s", "10 m/s", "15 m/s", "20 m/s"],
                answer="10 m/s",
                explanation="v = u + at = 0 + 2 × 5 = 10 m/s.",
                topic="Acceleration",
            ),
        ]

        return {
            "math-grade-10": Course(
                course_id="math-grade-10",
                title="Grade 10 Mathematics",
                category="School Curriculum",
                level="Grade 10",
                price="NPR 4,500",
                description="A structured mathematics course for school-level preparation.",
                lessons=[math_lesson_1, math_lesson_2],
                quiz_bank=math_questions,
            ),
            "neet-physics-foundation": Course(
                course_id="neet-physics-foundation",
                title="NEET Physics Foundation",
                category="Entrance Exam",
                level="Medical Entrance",
                price="NPR 8,000",
                description="Concept-based physics lessons and timed mock practice.",
                lessons=[physics_lesson],
                quiz_bank=physics_questions,
            ),
        }

    def add_superadmin(self, superadmin: SuperAdmin) -> None:
        self.superadmin = superadmin
        self.users[superadmin.user.user_id] = superadmin.user
        self.tenants.update(superadmin.tenants)

    def register_user(self, user_id: str, name: str, email: str, password: str, role: str, tenant_id: Optional[str] = None, approved: bool = True) -> User:
        user = User(user_id=user_id, name=name, email=email, password=password, role=role, tenant_id=tenant_id, approved=approved)
        self.users[user_id] = user
        return user

    def login(self, email: str, password: str) -> Optional[User]:
        for user in self.users.values():
            if user.email == email and user.password == password:
                if not user.approved:
                    return None
                user.online = True
                return user
        return None

    def create_tenant(self, company_name: str, tenant_type: str, meeting_provider: str = "Zoom") -> Tenant:
        if self.superadmin is None:
            raise ValueError("Super admin is required before tenant creation.")
        tenant = self.superadmin.create_tenant(company_name, tenant_type, meeting_provider)
        self.tenants[tenant.tenant_id] = tenant
        return tenant

    def enroll_student(self, user: User, course_id: str) -> str:
        if user.role != "student":
            return "Only students can enroll in courses."
        if course_id not in self.courses:
            return "Course not found."
        if course_id not in user.course_ids:
            user.course_ids.append(course_id)
        return f"{user.name} enrolled in {self.courses[course_id].title}."

    def evaluate_quiz(self, user: User, course_id: str, responses: Dict[str, str], time_taken: int = 0) -> Attempt:
        course = self.courses.get(course_id)
        if not course or course_id not in user.course_ids:
            raise ValueError("Student must be enrolled in the course before taking its quiz.")
        if not course.quiz_bank:
            raise ValueError("This course has no quiz questions yet.")

        correct = sum(
            1 for index, question in enumerate(course.quiz_bank)
            if responses.get(str(index)) == question.answer
        )
        weaknesses = sorted({
            question.topic
            for index, question in enumerate(course.quiz_bank)
            if responses.get(str(index)) != question.answer
        })
        score = round(correct / len(course.quiz_bank) * 100)
        previous_scores = [attempt.score for attempt in self.attempts.values() if attempt.course_id == course_id]
        percentile = round(sum(score >= previous for previous in previous_scores) / (len(previous_scores) + 1) * 100, 1)
        attempt = Attempt(
            attempt_id=f"attempt-{len(self.attempts) + 1}",
            user_id=user.user_id,
            course_id=course_id,
            responses=responses,
            score=score,
            total_marks=len(course.quiz_bank),
            weakness_tags=weaknesses,
            time_taken=max(0, time_taken),
            submitted_at="2026-09-03 00:00",
            percentile=percentile,
        )
        self.attempts[attempt.attempt_id] = attempt
        return attempt

    def add_live_class(self, class_id: str, title: str, tenant_id: str, instructor_id: str, scheduled_at: str, provider: str, join_url: Optional[str] = None, course_id: Optional[str] = None) -> LiveClass:
        if join_url is None:
            if provider.lower() == "zoom":
                join_url = f"https://zoom.us/j/{class_id.replace('-', '')[:9]}?pwd=gurukul"
            else:
                join_url = f"https://meet.google.com/{class_id.replace('-', '')[:10]}"

        live_class = LiveClass(
            class_id=class_id,
            title=title,
            tenant_id=tenant_id,
            instructor_id=instructor_id,
            course_id=course_id,
            scheduled_at=scheduled_at,
            provider=provider,
            join_url=join_url,
        )
        self.live_classes[class_id] = live_class
        return live_class

    def join_live_class(self, student_id: str, class_id: str) -> str:
        student = self.users.get(student_id)
        live_class = self.live_classes.get(class_id)
        if not student:
            return "Student not found."
        if not live_class:
            return "Live class not found."
        if student.role == "student" and student_id not in live_class.allowed_students:
            return "Your admin has not granted access to this class."
        if student.role == "student" and live_class.course_id and live_class.course_id not in student.course_ids:
            return "Enroll in this class subject before joining."
        instructor = self.users.get(live_class.instructor_id)
        if student.role == "student" and (not instructor or instructor.user_id not in live_class.attendees):
            return "The instructor must join the classroom before students can enter."
        if student_id not in live_class.attendees:
            live_class.attendees.append(student_id)
        student.online = True
        return f"{student.name} joined live class '{live_class.title}' on {live_class.provider}. Meeting link: {live_class.join_url}"

    def is_tenant_admin(self, user: Optional[User]) -> bool:
        return bool(user and user.role in ["admin", "tenant_admin", "superadmin"])

    def can_manage_user(self, admin: User, target: User) -> bool:
        return self.is_tenant_admin(admin) and (admin.role in {"admin", "superadmin"} or admin.tenant_id == target.tenant_id)

    def can_manage_class(self, admin: User, live_class: LiveClass) -> bool:
        return self.is_tenant_admin(admin) and (admin.role in {"admin", "superadmin"} or admin.tenant_id == live_class.tenant_id)

    def student_dashboard(self, user: User) -> Dict[str, Any]:
        enrolled = [self.courses[course_id].title for course_id in user.course_ids]
        live_classes = [cls.title for cls in self.live_classes.values() if user.user_id in cls.attendees]
        return {
            "name": user.name,
            "role": user.role,
            "enrolled_courses": enrolled,
            "live_classes": live_classes,
            "status": "online" if user.online else "offline",
        }

    def instructor_dashboard(self, user: User) -> Dict[str, Any]:
        hosted_classes = [cls for cls in self.live_classes.values() if cls.instructor_id == user.user_id]
        return {
            "name": user.name,
            "role": user.role,
            "hosted_classes": hosted_classes,
            "status": "online" if user.online else "offline",
        }

    def get_tenant(self, tenant_id: Optional[str]) -> Optional[Tenant]:
        if tenant_id is None:
            return None
        return self.tenants.get(tenant_id)


platform = OnlineClassPlatform()

super_admin = SuperAdmin(name="Software Engineer", email="superadmin@company.com", password="admin123")
super_admin.user.role = "admin"
platform.add_superadmin(super_admin)

# Seed tenant and users
bright = platform.create_tenant("BrightFuture Academy", "online_school", "Zoom")
skill = platform.create_tenant("SkillForge Institute", "training_institute", "Google Meet")

super_admin.define_tenant_workflow(bright, {"student_registration": True, "teacher_upload": True, "live_class": True, "quizzes": True, "attendance": True, "video_conference": "Zoom"})
super_admin.define_tenant_workflow(skill, {"student_registration": True, "demo_classes": True, "mentor_support": True, "video_conference": "Google Meet", "payment": True})

admin_user = platform.register_user("admin-01", "Priya Admin", "admin@brightfuture.com", "admin123", "admin", bright.tenant_id)
instructor_user = platform.register_user("inst-01", "Ramesh Teacher", "ramesh@brightfuture.com", "teacher123", "instructor", bright.tenant_id)
student_user = platform.register_user("stu-01", "Aarav Student", "aarav@student.com", "student123", "student", bright.tenant_id)
student_user.phone = "+9779800000000"

super_admin.assign_admin(bright, admin_user.user_id)
super_admin.assign_instructor(bright, instructor_user.user_id)
super_admin.assign_student(bright, student_user.user_id)

platform.enroll_student(student_user, "math-grade-10")
platform.enroll_student(student_user, "neet-physics-foundation")

live_class = platform.add_live_class(
        "class-101",
        "Physics Live Revision",
        bright.tenant_id,
        instructor_user.user_id,
        "2026-09-03 18:00",
        bright.meeting_provider,
        "https://zoom.us/j/987654321?pwd=gurukul",
        "neet-physics-foundation",
    )
live_class.allowed_students.append(student_user.user_id)
platform.join_live_class(student_user.user_id, live_class.class_id)


def get_dashboard_data(user: Optional[User]):
    if user is None:
        return {
            "name": "Guest",
            "role": "guest",
            "enrolled_courses": [],
            "live_classes": [],
            "status": "offline",
        }
    return platform.student_dashboard(user)


@app.route("/")
def index():
    return render_template("index.html", user=session.get("user"))


@app.post("/api/v1/auth/request-otp")
def api_request_otp():
    body = request.get_json(silent=True) or {}
    phone = str(body.get("phone", "")).strip()
    channel = body.get("channel", "sms")
    if not phone or channel not in {"sms", "whatsapp", "email"}:
        payload, status = api_response(message="A valid phone and channel are required.", success=False, status=400)
        return payload, status
    session_id = f"otp_sess_{secrets.token_hex(6)}"
    otp_sessions[session_id] = {
        "phone": phone,
        "code": os.getenv("GURUKUL_DEMO_OTP", "123456"),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=120),
    }
    payload, status = api_response(
        message="OTP sent successfully.",
        data={"session_id": session_id, "expires_in_seconds": 120},
    )
    return payload, status


@app.post("/api/v1/auth/verify-otp")
def api_verify_otp():
    body = request.get_json(silent=True) or {}
    record = otp_sessions.get(body.get("session_id"))
    if not record or record["phone"] != body.get("phone") or record["expires_at"] <= datetime.now(timezone.utc) or record["code"] != body.get("otp_code"):
        payload, status = api_response(message="Invalid or expired OTP.", success=False, status=401)
        return payload, status
    user = next((candidate for candidate in platform.users.values() if candidate.phone == record["phone"]), None)
    if not user:
        user = platform.register_user(f"usr_{secrets.token_hex(4)}", "New Student", "", "", "student", bright.tenant_id)
        user.phone = record["phone"]
    device_info = body.get("device_info") or {}
    user.device_tokens = [device_info["fcm_token"]] if device_info.get("fcm_token") else []
    access_token = secrets.token_urlsafe(32)
    refresh_token = secrets.token_urlsafe(32)
    api_tokens[access_token] = {"user_id": user.user_id, "expires_at": datetime.now(timezone.utc) + timedelta(hours=1)}
    api_tokens[refresh_token] = {"user_id": user.user_id, "expires_at": datetime.now(timezone.utc) + timedelta(days=30)}
    otp_sessions.pop(body.get("session_id"), None)
    payload, status = api_response(
        message="Authentication successful.",
        data={
            "tokens": {"access_token": access_token, "refresh_token": refresh_token, "expires_in": 3600},
            "user": {"id": user.user_id, "phone": user.phone, "full_name": user.name, "role": user.role, "profile_completed": bool(user.name)},
        },
    )
    return payload, status


@app.get("/api/v1/courses")
def api_list_courses():
    if not current_api_user():
        payload, status = api_response(message="Authentication required.", success=False, status=401)
        return payload, status
    category = request.args.get("category")
    courses = [course for course in platform.courses.values() if not category or course.category.lower().replace(" ", "_") == category.lower()]
    page = max(request.args.get("page", 1, type=int), 1)
    limit = min(max(request.args.get("limit", 10, type=int), 1), 50)
    start = (page - 1) * limit
    data = [public_course(course) for course in courses[start:start + limit]]
    total = len(courses)
    payload, status = api_response(data=data, meta={"page": page, "limit": limit, "total_records": total, "total_pages": (total + limit - 1) // limit})
    return payload, status


@app.get("/api/v1/courses/<course_id>/curriculum")
def api_course_curriculum(course_id):
    if not current_api_user():
        payload, status = api_response(message="Authentication required.", success=False, status=401)
        return payload, status
    course = platform.courses.get(course_id)
    if not course:
        payload, status = api_response(message="Course not found.", success=False, status=404)
        return payload, status
    lessons = []
    for index, lesson in enumerate(course.lessons, 1):
        lessons.append({"lesson_id": f"les_{course_id}_{index}", "title": lesson.title, "type": "video", "duration_seconds": int(lesson.duration.split()[0]) * 60, "is_preview": index == 1, "stream_url": None})
        lessons.append({"lesson_id": f"pdf_{course_id}_{index}", "title": f"Notes: {lesson.title}", "type": "pdf", "is_preview": index == 1, "pdf_url": None, "notes": lesson.notes, "audio_summary": lesson.audio_summary})
    payload, status = api_response(data={"course_id": course.course_id, "title": course.title, "modules": [{"module_id": f"mod_{course.course_id}", "title": course.category, "order": 1, "lessons": lessons}]})
    return payload, status


@app.get("/api/v1/assessments/<test_id>/start")
def api_start_assessment(test_id):
    user = current_api_user()
    if not user:
        payload, status = api_response(message="Authentication required.", success=False, status=401)
        return payload, status
    course = next((course for course in platform.courses.values() if course.quiz_bank and course.course_id in user.course_ids), None)
    if not course:
        payload, status = api_response(message="Assessment not found.", success=False, status=404)
        return payload, status
    attempt_id = f"att_{secrets.token_hex(5)}"
    api_attempts[attempt_id] = {"user_id": user.user_id, "test_id": test_id, "course_id": course.course_id}
    questions = [{"question_id": f"q_{100 + index}", "text": question.prompt, "marks": 2, "options": [{"option_id": f"opt_{chr(97 + option_index)}", "text": option} for option_index, option in enumerate(question.options)]} for index, question in enumerate(course.quiz_bank, 1)]
    payload, status = api_response(data={"test_id": test_id, "attempt_id": attempt_id, "title": f"{course.title} Mock Exam", "duration_minutes": 45, "total_questions": len(questions), "negative_marking_rate": 0.20, "questions": questions})
    return payload, status


@app.post("/api/v1/assessments/<test_id>/submit")
def api_submit_assessment(test_id):
    user = current_api_user()
    body = request.get_json(silent=True) or {}
    attempt = api_attempts.get(body.get("attempt_id"))
    if not user:
        payload, status = api_response(message="Authentication required.", success=False, status=401)
        return payload, status
    if not attempt or attempt["user_id"] != user.user_id or attempt["test_id"] != test_id:
        payload, status = api_response(message="Invalid assessment attempt.", success=False, status=400)
        return payload, status
    course = platform.courses[attempt["course_id"]]
    responses = {}
    for item in body.get("responses", []):
        question_id = item.get("question_id", "")
        try:
            question_index = int(question_id.split("_")[1]) - 101
        except (IndexError, TypeError, ValueError):
            payload, status = api_response(message="Each response must contain a valid question_id.", success=False, status=400)
            return payload, status
        if question_index < 0 or question_index >= len(course.quiz_bank):
            payload, status = api_response(message="Response contains an unknown question.", success=False, status=400)
            return payload, status
        responses[str(question_index)] = item.get("selected_option_id", "")
    correct = sum(1 for index, question in enumerate(course.quiz_bank) if responses.get(str(index)) == f"opt_{chr(97 + question.options.index(question.answer))}")
    attempted = len([response for response in responses.values() if response])
    incorrect = attempted - correct
    marks = correct * 2 - incorrect * 2 * 0.20
    result = {"attempt_id": body.get("attempt_id"), "score_summary": {"total_questions": len(course.quiz_bank), "attempted": attempted, "correct": correct, "incorrect": incorrect, "marks_obtained": round(marks, 2), "total_marks": len(course.quiz_bank) * 2.0, "accuracy_percentage": round(correct / attempted * 100, 1) if attempted else 0.0, "percentile": 0.0}, "weakness_analysis": [{"topic": question.topic, "status": "Needs Review", "recommendation": f"Review {question.topic} lessons"} for index, question in enumerate(course.quiz_bank) if responses.get(str(index)) != f"opt_{chr(97 + question.options.index(question.answer))}"]}
    api_attempts.pop(body.get("attempt_id"), None)
    payload, status = api_response(message="Test evaluation completed.", data=result, status=201)
    return payload, status


@app.post("/api/v1/live-sessions")
def api_schedule_live_session():
    user = current_api_user()
    body = request.get_json(silent=True) or {}
    if not user:
        payload, status = api_response(message="Authentication required.", success=False, status=401)
        return payload, status
    if user.role not in {"admin", "tenant_admin", "superadmin"}:
        payload, status = api_response(message="Only administrators can schedule sessions.", success=False, status=403)
        return payload, status
    course = platform.courses.get(body.get("course_id"))
    scheduled_start = parse_iso_datetime(body.get("scheduled_start_time"))
    duration = body.get("estimated_duration_minutes")
    if not course or not scheduled_start or not isinstance(duration, int) or duration < 1:
        payload, status = api_response(message="course_id, scheduled_start_time, and a positive duration are required.", success=False, status=400)
        return payload, status
    instructor_id = body.get("instructor_id")
    instructor = platform.users.get(instructor_id)
    if not instructor or instructor.role != "instructor" or not instructor.approved or instructor.tenant_id != user.tenant_id:
        payload, status = api_response(message="An approved instructor_id from your institute is required.", success=False, status=400)
        return payload, status
    session_id = f"sess_live_{secrets.token_hex(4)}"
    room_name = f"room_{course.course_id}_{secrets.token_hex(3)}"
    settings = body.get("settings") if isinstance(body.get("settings"), dict) else {}
    live_sessions[session_id] = {"session_id": session_id, "room_name": room_name, "course_id": course.course_id, "instructor_id": instructor.user_id, "title": body.get("title", "Live class"), "scheduled_start_time": scheduled_start.isoformat().replace("+00:00", "Z"), "estimated_duration_minutes": duration, "settings": settings, "status": "SCHEDULED", "attendees": set()}
    platform.add_live_class(session_id, live_sessions[session_id]["title"], user.tenant_id or "tenant-1", instructor.user_id, live_sessions[session_id]["scheduled_start_time"], "SFU WebRTC", url_for("meeting", room_id=session_id, _external=True), course.course_id)
    payload, status = api_response(data={"session_id": session_id, "room_name": room_name, "scheduled_start_time": live_sessions[session_id]["scheduled_start_time"], "status": "SCHEDULED"}, status=201)
    return payload, status


@app.post("/api/v1/live-sessions/<session_id>/join")
def api_join_live_session(session_id):
    user = current_api_user()
    live_session = live_sessions.get(session_id)
    if not user:
        payload, status = api_response(message="Authentication required.", success=False, status=401)
        return payload, status
    if not live_session:
        payload, status = api_response(message="Live session not found.", success=False, status=404)
        return payload, status
    if live_session["status"] in {"ENDED", "CANCELLED"}:
        payload, status = api_response(message="This live session is no longer available.", success=False, status=409)
        return payload, status
    if user.user_id != live_session["instructor_id"] and live_session["course_id"] not in user.course_ids:
        payload, status = api_response(message="Enroll in the course before joining this session.", success=False, status=403)
        return payload, status
    classroom = platform.live_classes.get(session_id)
    instructor = platform.users.get(live_session["instructor_id"])
    if user.role == "student" and (not classroom or not instructor or instructor.user_id not in classroom.attendees):
        payload, status = api_response(message="The instructor must join before students can enter.", success=False, status=409)
        return payload, status
    room_token = secrets.token_urlsafe(32)
    room_tokens[room_token] = {"user_id": user.user_id, "session_id": session_id, "expires_at": datetime.now(timezone.utc) + timedelta(hours=2)}
    live_session["attendees"].add(user.user_id)
    payload, status = api_response(data={"session_id": session_id, "connection_type": "sfu_webrtc", "sfu_ws_url": os.getenv("GURUKUL_SFU_WS_URL", "wss://sfu.localhost"), "room_token": room_token, "user_role": "publisher" if user.user_id == live_session["instructor_id"] else "subscriber"})
    return payload, status


@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    user = platform.login(email, password)
    if user is None:
        return render_template("index.html", error="Invalid email or password.")
    session["user_id"] = user.user_id
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
def dashboard():
    user_id = session.get("user_id")
    user = platform.users.get(user_id)
    if not user:
        return redirect(url_for("index"))

    dashboard_data = get_dashboard_data(user)
    tenant = platform.get_tenant(user.tenant_id)
    course_list = [course for course in platform.courses.values() if course.tenant_id in [None, user.tenant_id]]
    live_list = [live for live in platform.live_classes.values() if live.tenant_id == user.tenant_id and (user.role in {"admin", "tenant_admin", "superadmin"} or (user.role == "instructor" and live.instructor_id == user.user_id) or (user.role == "student" and user.user_id in live.allowed_students))]
    instructor_dashboard = platform.instructor_dashboard(user) if user.role == "instructor" else None
    assessments = [
        {"course": course, "attempts": [attempt for attempt in platform.attempts.values() if attempt.user_id == user.user_id and attempt.course_id == course.course_id]}
        for course in course_list if course.quiz_bank and course.course_id in user.course_ids
    ]
    managed_users = [candidate for candidate in platform.users.values() if candidate.tenant_id == user.tenant_id and candidate.user_id != user.user_id] if platform.is_tenant_admin(user) else []
    managed_classes = [live for live in platform.live_classes.values() if platform.can_manage_class(user, live)] if platform.is_tenant_admin(user) else []
    student_count = sum(1 for candidate in managed_users if candidate.role == "student")
    instructor_count = sum(1 for candidate in managed_users if candidate.role == "instructor")
    return render_template(
        "dashboard.html",
        user=user,
        tenant=tenant,
        dashboard=dashboard_data,
        instructor_dashboard=instructor_dashboard,
        courses=course_list,
        live_classes=live_list,
        managed_users=managed_users,
        managed_classes=managed_classes,
        assessments=assessments,
        student_count=student_count,
        instructor_count=instructor_count,
        message=request.args.get("message", ""),
    )


@app.route("/assessment/<course_id>")
def assessment(course_id):
    user = platform.users.get(session.get("user_id"))
    course = platform.courses.get(course_id)
    if not user:
        return redirect(url_for("index"))
    if not course or course_id not in user.course_ids:
        return redirect(url_for("dashboard", message="Enroll in this course before starting its quiz."))
    return render_template("assessment.html", user=user, course=course)


@app.route("/assessment/<course_id>/submit", methods=["POST"])
def submit_assessment(course_id):
    user = platform.users.get(session.get("user_id"))
    course = platform.courses.get(course_id)
    if not user or not course or course_id not in user.course_ids:
        return redirect(url_for("index"))
    responses = {str(index): request.form.get(f"question_{index}", "") for index in range(len(course.quiz_bank))}
    try:
        time_taken = int(request.form.get("time_taken", 0))
    except ValueError:
        time_taken = 0
    try:
        attempt = platform.evaluate_quiz(user, course_id, responses, time_taken)
    except ValueError as error:
        return redirect(url_for("dashboard", message=str(error)))
    return render_template("assessment_result.html", user=user, course=course, attempt=attempt)


@app.route("/admin/create-user", methods=["POST"])
def admin_create_user():
    admin_id = session.get("user_id")
    admin = platform.users.get(admin_id)
    if not admin or not platform.is_tenant_admin(admin):
        return redirect(url_for("index"))
    role = request.form.get("role", "student")
    if role not in ["student", "instructor"]:
        return redirect(url_for("dashboard", message="Only student and instructor accounts can be created here."))
    user_id = f"{role[:4]}-{len(platform.users) + 1}"
    created = platform.register_user(user_id, request.form.get("name", ""), request.form.get("email", ""), request.form.get("password", ""), role, admin.tenant_id, approved=False)
    tenant = platform.get_tenant(admin.tenant_id)
    if tenant:
        (tenant.students if role == "student" else tenant.instructors).append(created.user_id)
    return redirect(url_for("dashboard", message=f"{role.title()} account created and is waiting for approval."))


@app.route("/admin/approve-user", methods=["POST"])
def admin_approve_user():
    admin = platform.users.get(session.get("user_id"))
    target = platform.users.get(request.form.get("user_id"))
    if not admin or not target or not platform.can_manage_user(admin, target):
        return redirect(url_for("index"))
    target.approved = True
    return redirect(url_for("dashboard", message=f"{target.name} is approved."))


@app.route("/admin/create-course", methods=["POST"])
def admin_create_course():
    admin = platform.users.get(session.get("user_id"))
    if not admin or not platform.is_tenant_admin(admin):
        return redirect(url_for("index"))
    course_id = request.form.get("course_id", "").strip() or f"course-{len(platform.courses) + 1}"
    platform.courses[course_id] = Course(
        course_id=course_id,
        title=request.form.get("title", "New Course"),
        category=request.form.get("category", "General"),
        level=request.form.get("level", "All levels"),
        price=request.form.get("price", "Free"),
        description=request.form.get("description", ""),
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
    )
    return redirect(url_for("dashboard", message="Course created."))


@app.route("/admin/create-class", methods=["POST"])
def admin_create_class():
    admin = platform.users.get(session.get("user_id"))
    if not admin or not platform.is_tenant_admin(admin):
        return redirect(url_for("index"))
    instructor_id = request.form.get("instructor_id")
    course_id = request.form.get("course_id")
    instructor = platform.users.get(instructor_id)
    if not instructor or instructor.role != "instructor" or not instructor.approved or instructor.tenant_id != admin.tenant_id or course_id not in platform.courses:
        return redirect(url_for("dashboard", message="Choose an approved instructor from your institute."))
    class_id = request.form.get("class_id", "").strip() or f"class-{len(platform.live_classes) + 101}"
    live = platform.add_live_class(class_id, request.form.get("title", "Live Class"), admin.tenant_id, instructor_id, request.form.get("scheduled_at", ""), "Gurukul Classroom", url_for("meeting", room_id=class_id, _external=True), course_id)
    live.allowed_students = request.form.getlist("student_ids")
    return redirect(url_for("dashboard", message="Scheduled classroom created with student access."))


@app.route("/admin/update-access", methods=["POST"])
def admin_update_access():
    admin = platform.users.get(session.get("user_id"))
    live = platform.live_classes.get(request.form.get("class_id"))
    if not admin or not live or not platform.can_manage_class(admin, live):
        return redirect(url_for("index"))
    live.allowed_students = request.form.getlist("student_ids")
    return redirect(url_for("dashboard", message="Class access updated."))


@app.route("/enroll", methods=["POST"])
def enroll():
    user_id = session.get("user_id")
    user = platform.users.get(user_id)
    if not user:
        return redirect(url_for("index"))
    course_id = request.form.get("course_id")
    if course_id:
        platform.enroll_student(user, course_id)
    return redirect(url_for("dashboard"))


@app.route("/create-class", methods=["POST"])
def create_class():
    user_id = session.get("user_id")
    user = platform.users.get(user_id)
    if not user or not platform.is_tenant_admin(user):
        return redirect(url_for("index"))

    title = request.form.get("title", "")
    scheduled_at = request.form.get("scheduled_at", "")
    provider = request.form.get("provider", "Zoom")
    course_id = request.form.get("course_id")
    class_id = request.form.get("class_id", f"class-{len(platform.live_classes) + 101}")

    if title and scheduled_at:
        platform.add_live_class(
            class_id=class_id,
            title=title,
            tenant_id=user.tenant_id or "tenant-1",
            instructor_id=user.user_id,
            scheduled_at=scheduled_at,
            provider=provider,
            course_id=course_id,
        )

    return redirect(url_for("dashboard"))


@app.route("/join-class", methods=["POST"])
def join_class():
    user_id = session.get("user_id")
    user = platform.users.get(user_id)
    if not user:
        return redirect(url_for("index"))
    class_id = request.form.get("class_id")
    live_class = platform.live_classes.get(class_id)
    if not live_class or (user.role == "instructor" and live_class.instructor_id != user.user_id) or (user.role == "student" and (user.user_id not in live_class.allowed_students or (live_class.course_id and live_class.course_id not in user.course_ids))):
        return redirect(url_for("dashboard", message="You do not have access to this scheduled class."))
    if class_id:
        join_message = platform.join_live_class(user.user_id, class_id)
        if join_message.startswith("The instructor must"):
            return redirect(url_for("dashboard", message=join_message))
    room_id = class_id or "room-default"
    return redirect(url_for("meeting", room_id=room_id))


@app.route("/meeting/<room_id>")
def meeting(room_id):
    user_id = session.get("user_id")
    user = platform.users.get(user_id)
    if not user:
        return redirect(url_for("index"))
    live_class = platform.live_classes.get(room_id)
    if not live_class or (user.role == "instructor" and live_class.instructor_id != user.user_id) or (user.role == "student" and (user.user_id not in live_class.allowed_students or (live_class.course_id and live_class.course_id not in user.course_ids))):
        return redirect(url_for("dashboard", message="This classroom is not assigned to your account."))
    return render_template(
        "meeting.html",
        user=user,
        room_id=room_id,
        is_host=user.user_id == live_class.instructor_id,
        scheduled_instructor=platform.users.get(live_class.instructor_id),
    )


@app.post("/api/v1/live-sessions/<session_id>/livekit-token")
def livekit_token_bridge(session_id):
    user = platform.users.get(session.get("user_id"))
    live_class = platform.live_classes.get(session_id)
    service_url = os.getenv("LIVEKIT_SERVICE_URL", "").rstrip("/")
    if not user or not live_class:
        return {"success": False, "message": "Live session not found."}, 404
    if user.role == "student" and (user.user_id not in live_class.allowed_students or (live_class.course_id and live_class.course_id not in user.course_ids)):
        return {"success": False, "message": "You do not have access to this live session."}, 403
    instructor = platform.users.get(live_class.instructor_id)
    if user.role == "student" and (not instructor or instructor.user_id not in live_class.attendees):
        return {"success": False, "message": "The instructor must join before students can enter."}, 409
    if not service_url:
        return {"success": False, "message": "LiveKit service is not configured."}, 503
    payload = json.dumps({
        "roomName": session_id,
        "identity": user.user_id,
        "userName": user.name,
        "isInstructor": user.user_id == live_class.instructor_id,
    }).encode("utf-8")
    try:
        request = Request(f"{service_url}/api/v1/livekit/token", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except (HTTPError, URLError, TimeoutError, ValueError):
        return {"success": False, "message": "LiveKit service is unavailable."}, 502


@socketio.on("join_room")
def handle_join_room(data):
    room_id = data.get("room")
    username = data.get("username", "Guest")
    role = data.get("role", "student")
    is_host = data.get("is_host", False)
    live_class = platform.live_classes.get(room_id)
    user = platform.users.get(session.get("user_id"))
    is_verified_host = bool(live_class and user and user.user_id == live_class.instructor_id and is_host)
    if not room_id:
        return
    join_room(room_id)
    room_members[room_id][request.sid] = {"username": username, "role": role}

    if is_verified_host:
        room_hosts[room_id] = request.sid

    host_id = room_hosts.get(room_id)
    emit("room_host", {"hostId": host_id, "hostName": room_members[room_id].get(host_id, {}).get("username", "Instructor") if host_id else None}, room=room_id)
    emit("room_users", {"users": room_members[room_id]}, room=room_id)
    emit("system_message", {"text": f"{username} joined the room."}, room=room_id)
    emit("user-joined", {"userId": request.sid, "username": username, "role": role}, room=room_id, include_self=False)


@socketio.on("signal")
def handle_signal(data):
    target = data.get("target")
    if target:
        emit("signal", data, room=target)


@socketio.on("chat_message")
def handle_chat_message(data):
    room_id = data.get("room")
    username = data.get("username", "Guest")
    text = data.get("text", "")
    if room_id and text:
        emit("chat_message", {"username": username, "text": text}, room=room_id)


@socketio.on("whiteboard_update")
def handle_whiteboard_update(data):
    room_id = data.get("room")
    if room_id:
        emit("whiteboard_update", data, room=room_id, include_self=False)


@socketio.on("disconnect")
def handle_disconnect():
    for room_id, members in list(room_members.items()):
        if request.sid in members:
            username = members.pop(request.sid)
            if room_hosts.get(room_id) == request.sid:
                room_hosts.pop(room_id, None)
                emit("room_host", {"hostId": None, "hostName": None}, room=room_id)
            emit("system_message", {"text": f"{username['username']} left the room."}, room=room_id)
            emit("user-left", {"userId": request.sid}, room=room_id)
            emit("room_users", {"users": members}, room=room_id)
            if not members:
                room_members.pop(room_id, None)


if __name__ == "__main__":
    ssl_context = "adhoc" if os.getenv("GURUKUL_HTTPS") == "1" else None
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, ssl_context=ssl_context)
