from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


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
    lessons: List[Lesson] = field(default_factory=list)
    quiz_bank: List[Question] = field(default_factory=list)


@dataclass
class User:
    user_id: str
    name: str
    email: str
    password: str
    role: str
    tenant_id: Optional[str] = None
    online: bool = False
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
    scheduled_at: str
    provider: str
    attendees: List[str] = field(default_factory=list)
    status: str = "scheduled"


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

    def create_tenant(
        self,
        company_name: str,
        tenant_type: str,
        meeting_provider: str = "Zoom",
    ) -> Tenant:
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
        self.superadmin = None

    def _build_courses(self) -> Dict[str, Course]:
        math_lesson_1 = Lesson(
            title="Algebra Basics",
            duration="18 min",
            notes="Learn variables and solve linear equations.",
            audio_summary="Quick revision of algebraic rules.",
        )
        math_lesson_2 = Lesson(
            title="Quadratic Equations",
            duration="22 min",
            notes="Factorization and formula-based solving.",
            audio_summary="Short revision on roots and factoring.",
        )
        physics_lesson = Lesson(
            title="Kinematics",
            duration="25 min",
            notes="Velocity, acceleration, and graph-based solving.",
            audio_summary="Key laws of motion with examples.",
        )

        math_questions = [
            Question(
                prompt="Solve: 3x + 7 = 19",
                options=["x = 2", "x = 3", "x = 4", "x = 5"],
                answer="x = 4",
                explanation="Subtract 7 and divide by 3.",
                topic="Algebra",
            ),
            Question(
                prompt="What are the roots of x^2 - 5x + 6 = 0?",
                options=["1 and 6", "2 and 3", "-2 and -3", "-1 and -6"],
                answer="2 and 3",
                explanation="The equation factors as (x - 2)(x - 3) = 0.",
                topic="Quadratics",
            ),
        ]

        physics_questions = [
            Question(
                prompt="A car moves 20 m in 4 s. What is its average speed?",
                options=["4 m/s", "5 m/s", "6 m/s", "8 m/s"],
                answer="5 m/s",
                explanation="Average speed = distance / time.",
                topic="Motion",
            ),
            Question(
                prompt="If an object accelerates from rest at 2 m/s^2 for 5 s, what is its velocity?",
                options=["5 m/s", "10 m/s", "15 m/s", "20 m/s"],
                answer="10 m/s",
                explanation="v = u + at.",
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
                description="Structured curriculum support for school mathematics.",
                lessons=[math_lesson_1, math_lesson_2],
                quiz_bank=math_questions,
            ),
            "neet-physics-foundation": Course(
                course_id="neet-physics-foundation",
                title="NEET Physics Foundation",
                category="Entrance Exam",
                level="Medical Entrance",
                price="NPR 8,000",
                description="Conceptual learning and practice for entrance exam preparation.",
                lessons=[physics_lesson],
                quiz_bank=physics_questions,
            ),
        }

    def add_superadmin(self, superadmin: SuperAdmin) -> None:
        self.superadmin = superadmin
        self.users[superadmin.user.user_id] = superadmin.user
        self.tenants.update(superadmin.tenants)

    def register_user(
        self,
        user_id: str,
        name: str,
        email: str,
        password: str,
        role: str,
        tenant_id: Optional[str] = None,
    ) -> User:
        user = User(
            user_id=user_id,
            name=name,
            email=email,
            password=password,
            role=role,
            tenant_id=tenant_id,
        )
        self.users[user_id] = user
        return user

    def login(self, email: str, password: str) -> Optional[User]:
        for user in self.users.values():
            if user.email == email and user.password == password:
                user.online = True
                return user
        return None

    def get_user(self, user_id: str) -> Optional[User]:
        return self.users.get(user_id)

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

    def add_live_class(
        self,
        class_id: str,
        title: str,
        tenant_id: str,
        instructor_id: str,
        scheduled_at: str,
        provider: str,
    ) -> LiveClass:
        live_class = LiveClass(
            class_id=class_id,
            title=title,
            tenant_id=tenant_id,
            instructor_id=instructor_id,
            scheduled_at=scheduled_at,
            provider=provider,
        )
        self.live_classes[class_id] = live_class
        return live_class

    def join_live_class(self, student_id: str, class_id: str) -> str:
        student = self.get_user(student_id)
        live_class = self.live_classes.get(class_id)
        if not student:
            return "Student not found."
        if not live_class:
            return "Live class not found."
        if student_id not in live_class.attendees:
            live_class.attendees.append(student_id)
        student.online = True
        return f"{student.name} joined live class '{live_class.title}' on {live_class.provider}."

    def student_dashboard(self, user: User) -> Dict[str, Any]:
        enrolled = [self.courses[course_id].title for course_id in user.course_ids]
        live_classes = [
            cls.title for cls in self.live_classes.values()
            if user.user_id in cls.attendees
        ]
        return {
            "name": user.name,
            "role": user.role,
            "enrolled_courses": enrolled,
            "live_classes": live_classes,
            "status": "online" if user.online else "offline",
        }

    def print_tenant_summary(self) -> None:
        print("\nTenant summary")
        print("=" * 20)
        for tenant in self.tenants.values():
            print(f"- {tenant.company_name} | Type: {tenant.tenant_type} | Provider: {tenant.meeting_provider}")
            print(f"  Workflow: {tenant.workflow}")


class DemoSystem:
    def run(self):
        platform = OnlineClassPlatform()

        super_admin = SuperAdmin(
            name="Software Engineer",
            email="superadmin@company.com",
            password="admin123",
        )
        platform.add_superadmin(super_admin)

        tenant_a = platform.create_tenant("BrightFuture Academy", "online_school")
        tenant_b = platform.create_tenant("SkillForge Institute", "training_institute", "Google Meet")

        super_admin.define_tenant_workflow(
            tenant_a,
            {
                "student_registration": True,
                "teacher_upload": True,
                "live_class": True,
                "quizzes": True,
                "attendance": True,
                "video_conference": "Zoom",
            },
        )
        super_admin.define_tenant_workflow(
            tenant_b,
            {
                "student_registration": True,
                "demo_classes": True,
                "mentor_support": True,
                "video_conference": "Google Meet",
                "payment": True,
            },
        )

        admin_user = platform.register_user(
            "admin-01",
            "Priya Admin",
            "admin@brightfuture.com",
            "admin123",
            "tenant_admin",
            tenant_id=tenant_a.tenant_id,
        )
        instructor_user = platform.register_user(
            "inst-01",
            "Ramesh Teacher",
            "ramesh@brightfuture.com",
            "teacher123",
            "instructor",
            tenant_id=tenant_a.tenant_id,
        )
        student_user = platform.register_user(
            "stu-01",
            "Aarav Student",
            "aarav@student.com",
            "student123",
            "student",
            tenant_id=tenant_a.tenant_id,
        )

        super_admin.assign_admin(tenant_a, admin_user.user_id)
        super_admin.assign_instructor(tenant_a, instructor_user.user_id)
        super_admin.assign_student(tenant_a, student_user.user_id)

        platform.enroll_student(student_user, "math-grade-10")
        platform.enroll_student(student_user, "neet-physics-foundation")

        live_class = platform.add_live_class(
            "class-101",
            "Physics Live Revision",
            tenant_a.tenant_id,
            instructor_user.user_id,
            "2026-09-03 18:00",
            tenant_a.meeting_provider,
        )

        result = platform.join_live_class(student_user.user_id, live_class.class_id)

        print("Gurukul Next Multi-Tenant Learning Platform")
        print("=" * 50)
        print("Super Admin:", super_admin.user.name)
        print("Role:", super_admin.user.role)
        print()
        platform.print_tenant_summary()
        print()
        print("Login Test:")
        logged_in = platform.login("aarav@student.com", "student123")
        print(f"Student login successful: {logged_in.name if logged_in else 'No'}")
        print()
        print("Class Join:")
        print(result)
        print()
        print("Student Dashboard:")
        print(platform.student_dashboard(student_user))
        print()
        print("Live Class Details:")
        print(live_class)


if __name__ == "__main__":
    DemoSystem().run()
