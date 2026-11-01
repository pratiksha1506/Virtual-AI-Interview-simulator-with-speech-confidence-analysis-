import sqlite3
import hashlib
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from .config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def hash_password(password: str, salt: Optional[str] = None) -> str:
    if not salt:
        salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}${dk.hex()}"

def verify_password(password: str, hashed_str: str) -> bool:
    if not hashed_str or "$" not in hashed_str:
        return False
    salt, dk_hex = hashed_str.split("$", 1)
    test_dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return test_dk.hex() == dk_hex

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Users
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'job_seeker', -- 'job_seeker' or 'admin'
        created_at TEXT NOT NULL
    )
    """)

    # Interviews
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        admin_id INTEGER,
        job_role TEXT NOT NULL,
        experience_level TEXT NOT NULL DEFAULT 'Mid-Level',
        interview_type TEXT NOT NULL DEFAULT 'Technical',
        difficulty TEXT NOT NULL DEFAULT 'Medium',
        question_count INTEGER NOT NULL DEFAULT 5,
        duration_minutes INTEGER NOT NULL DEFAULT 15,
        camera_enabled INTEGER NOT NULL DEFAULT 0,
        resume_text TEXT,
        scheduled_date TEXT,
        scheduled_time TEXT,
        status TEXT NOT NULL DEFAULT 'in_progress', -- 'scheduled', 'in_progress', 'completed', 'cancelled', 'not_attended'
        started_at TEXT,
        completed_at TEXT,
        final_score INTEGER,
        score INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY (candidate_id) REFERENCES users(id)
    )
    """)

    # Questions asked during the interview
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER NOT NULL,
        sequence_num INTEGER NOT NULL,
        question_text TEXT NOT NULL,
        question_type TEXT NOT NULL,
        topic TEXT,
        difficulty TEXT NOT NULL,
        expected_keywords TEXT,
        context_notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )
    """)

    # Candidate responses per question
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        transcript TEXT NOT NULL,
        duration_seconds REAL NOT NULL DEFAULT 0,
        content_score INTEGER,
        technical_score INTEGER,
        communication_score INTEGER,
        problem_solving_score INTEGER,
        facial_score INTEGER,
        overall_score INTEGER,
        feedback_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (interview_id) REFERENCES interviews(id),
        FOREIGN KEY (question_id) REFERENCES questions(id)
    )
    """)

    # Final comprehensive report
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        interview_id INTEGER UNIQUE NOT NULL,
        overall_score INTEGER NOT NULL,
        content_score INTEGER NOT NULL,
        technical_score INTEGER NOT NULL,
        communication_score INTEGER NOT NULL,
        problem_solving_score INTEGER NOT NULL,
        scoring_engine TEXT NOT NULL,
        strengths_json TEXT,
        weaknesses_json TEXT,
        recommendations_json TEXT,
        practice_exercises_json TEXT,
        model_answers_json TEXT,
        presentation_obs_json TEXT,
        overall_feedback TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (interview_id) REFERENCES interviews(id)
    )
    """)

    # Settings table for persistent admin configuration
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    # Ensure final_score and score columns exist in interviews table
    cursor.execute("PRAGMA table_info(interviews)")
    cols = [r["name"] for r in cursor.fetchall()]
    if "final_score" not in cols:
        cursor.execute("ALTER TABLE interviews ADD COLUMN final_score INTEGER")
    if "score" not in cols:
        cursor.execute("ALTER TABLE interviews ADD COLUMN score INTEGER")

    conn.commit()

    # Seed default question count if not present
    cursor.execute("SELECT key FROM settings WHERE key = 'default_question_count'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('default_question_count', '10', ?)",
            (datetime.utcnow().isoformat(),)
        )
        conn.commit()

    # Seed demo admin if not present
    cursor.execute("SELECT id FROM users WHERE email = 'admin@demo.com'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Demo Admin", "admin@demo.com", hash_password("admin123"), "admin", datetime.utcnow().isoformat())
        )
        conn.commit()

    # Seed registered candidate Prathiksha H M if not present (permanent candidate preservation)
    cursor.execute("SELECT id FROM users WHERE email = 'pratikshahm1506@gmail.com'")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Prathiksha H M", "pratikshahm1506@gmail.com", hash_password("prathiksha123"), "job_seeker", datetime.utcnow().isoformat())
        )
        conn.commit()

    conn.close()

# User helpers
def create_user(name: str, email: str, password: str, role: str = "job_seeker") -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    clean_email = email.lower().strip()
    clean_name = name.strip()
    try:
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (clean_name, clean_email, hash_password(password), role, created_at)
        )
        conn.commit()
        user_id = cursor.lastrowid
        return {"id": user_id, "name": clean_name, "email": clean_email, "role": role, "createdAt": created_at}
    except sqlite3.IntegrityError:
        raise ValueError("An account with this email already exists.")
    finally:
        conn.close()

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, role, created_at FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_candidates() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, role, created_at FROM users WHERE role = 'job_seeker' ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_user_and_data(user_id: int) -> bool:
    """Safely cascades and deletes all associated records for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM interviews WHERE candidate_id = ?", (user_id,))
    int_ids = [r[0] for r in cursor.fetchall()]
    if int_ids:
        placeholders = ','.join('?' for _ in int_ids)
        cursor.execute(f"DELETE FROM reports WHERE interview_id IN ({placeholders})", int_ids)
        cursor.execute(f"DELETE FROM responses WHERE interview_id IN ({placeholders})", int_ids)
        cursor.execute(f"DELETE FROM questions WHERE interview_id IN ({placeholders})", int_ids)
        cursor.execute(f"DELETE FROM interviews WHERE id IN ({placeholders})", int_ids)
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True

# Interview helpers
def create_interview(candidate_id: int, job_role: str, experience_level: str, interview_type: str,
                     difficulty: str, question_count: int, duration_minutes: int, camera_enabled: bool,
                     resume_text: Optional[str] = None, status: str = "in_progress",
                     scheduled_date: Optional[str] = None, scheduled_time: Optional[str] = None,
                     admin_id: Optional[int] = None) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()

    # Validate that candidate exists and is a registered job seeker
    cursor.execute("SELECT id, role FROM users WHERE id = ?", (candidate_id,))
    cand = cursor.fetchone()
    if not cand or cand["role"] != "job_seeker":
        conn.close()
        raise ValueError(f"Cannot create interview: candidate ID {candidate_id} does not exist or is not a registered job seeker.")

    now = datetime.utcnow().isoformat()
    started_at = now if status == "in_progress" else None

    cursor.execute("""
    INSERT INTO interviews (candidate_id, admin_id, job_role, experience_level, interview_type,
                            difficulty, question_count, duration_minutes, camera_enabled,
                            resume_text, scheduled_date, scheduled_time, status, started_at, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (candidate_id, admin_id, job_role, experience_level, interview_type,
          difficulty, question_count, duration_minutes, 1 if camera_enabled else 0,
          resume_text, scheduled_date, scheduled_time, status, started_at, now))
    conn.commit()
    interview_id = cursor.lastrowid
    conn.close()
    return get_interview_by_id(interview_id)

def get_interview_by_id(interview_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["camera_enabled"] = bool(d["camera_enabled"])
    return d

def update_interview_status(interview_id: int, status: str, completed_at: Optional[str] = None, started_at: Optional[str] = None, final_score: Optional[int] = None):
    conn = get_connection()
    cursor = conn.cursor()
    if completed_at:
        if final_score is not None:
            cursor.execute("UPDATE interviews SET status = ?, completed_at = ?, final_score = ?, score = ? WHERE id = ?", (status, completed_at, final_score, final_score, interview_id))
        else:
            cursor.execute("UPDATE interviews SET status = ?, completed_at = ? WHERE id = ?", (status, completed_at, interview_id))
    elif status == "in_progress":
        now = started_at or datetime.utcnow().isoformat()
        cursor.execute("UPDATE interviews SET status = ?, started_at = COALESCE(started_at, ?) WHERE id = ?", (status, now, interview_id))
    else:
        cursor.execute("UPDATE interviews SET status = ? WHERE id = ?", (status, interview_id))
    conn.commit()
    conn.close()

def delete_interview_record(interview_id: int) -> bool:
    """Safely deletes an interview record and its responses, questions, and report. NEVER deletes candidate users."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reports WHERE interview_id = ?", (interview_id,))
    cursor.execute("DELETE FROM responses WHERE interview_id = ?", (interview_id,))
    cursor.execute("DELETE FROM questions WHERE interview_id = ?", (interview_id,))
    cursor.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))
    conn.commit()
    conn.close()
    return True

def clear_all_interview_history() -> int:
    """Safely removes all interview records and history from the system. Registered candidate accounts are 100% preserved."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reports")
    cursor.execute("DELETE FROM responses")
    cursor.execute("DELETE FROM questions")
    cursor.execute("DELETE FROM interviews")
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

def get_interviews_for_candidate(candidate_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT i.*, 
           r.overall_score as report_overall_score,
           r.technical_score as report_technical_score,
           r.communication_score as report_communication_score
    FROM interviews i 
    LEFT JOIN reports r ON i.id = r.interview_id
    WHERE i.candidate_id = ? 
    ORDER BY i.id DESC
    """, (candidate_id,))
    rows = cursor.fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["camera_enabled"] = bool(d["camera_enabled"])
        if d.get("final_score") is None and d.get("report_overall_score") is not None:
            d["final_score"] = d["report_overall_score"]
            d["score"] = d["report_overall_score"]
        res.append(d)
    return res

def get_all_interviews() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT i.*, u.name as candidate_name, u.email as candidate_email,
           r.overall_score as report_overall_score,
           r.technical_score as report_technical_score,
           r.communication_score as report_communication_score
    FROM interviews i 
    JOIN users u ON i.candidate_id = u.id 
    LEFT JOIN reports r ON i.id = r.interview_id
    ORDER BY i.id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["camera_enabled"] = bool(d["camera_enabled"])
        if d.get("final_score") is None and d.get("report_overall_score") is not None:
            d["final_score"] = d["report_overall_score"]
            d["score"] = d["report_overall_score"]
        res.append(d)
    return res

def get_interview_full_details(interview_id: int) -> Optional[Dict[str, Any]]:
    """Returns an interview with candidate details, questions, answers, individual scores, and report."""
    interview = get_interview_by_id(interview_id)
    if not interview:
        return None
    candidate = get_user_by_id(interview["candidate_id"])
    questions = get_questions_for_interview(interview_id)
    responses = get_responses_for_interview(interview_id)
    report = get_report_by_interview_id(interview_id)
    return {
        "interview": interview,
        "candidate": candidate,
        "questions": questions,
        "responses": responses,
        "report": report
    }

# Question helpers
def add_question(interview_id: int, sequence_num: int, question_text: str, question_type: str,
                 topic: str, difficulty: str, expected_keywords: str = "", context_notes: str = "") -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO questions (interview_id, sequence_num, question_text, question_type, topic, difficulty, expected_keywords, context_notes, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (interview_id, sequence_num, question_text, question_type, topic, difficulty, expected_keywords, context_notes, now))
    conn.commit()
    qid = cursor.lastrowid
    conn.close()
    return {
        "id": qid,
        "interview_id": interview_id,
        "sequence_num": sequence_num,
        "question_text": question_text,
        "question_type": question_type,
        "topic": topic,
        "difficulty": difficulty,
        "expected_keywords": expected_keywords,
        "context_notes": context_notes,
    }

def get_questions_for_interview(interview_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE interview_id = ? ORDER BY sequence_num ASC", (interview_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_question_by_id(question_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# Response helpers
def add_response(interview_id: int, question_id: int, transcript: str, duration_seconds: float,
                 content_score: int, technical_score: int, communication_score: int,
                 problem_solving_score: int, facial_score: Optional[int], overall_score: int,
                 feedback: Dict[str, Any]) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    feedback_str = json.dumps(feedback)
    cursor.execute("""
    INSERT INTO responses (interview_id, question_id, transcript, duration_seconds,
                           content_score, technical_score, communication_score,
                           problem_solving_score, facial_score, overall_score, feedback_json, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (interview_id, question_id, transcript, duration_seconds,
          content_score, technical_score, communication_score, problem_solving_score,
          facial_score, overall_score, feedback_str, now))
    conn.commit()
    rid = cursor.lastrowid
    conn.close()
    return {
        "id": rid,
        "interview_id": interview_id,
        "question_id": question_id,
        "transcript": transcript,
        "duration_seconds": duration_seconds,
        "content_score": content_score,
        "technical_score": technical_score,
        "communication_score": communication_score,
        "problem_solving_score": problem_solving_score,
        "facial_score": facial_score,
        "overall_score": overall_score,
        "feedback": feedback
    }

def get_responses_for_interview(interview_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT r.*, q.question_text, q.question_type, q.topic, q.difficulty 
    FROM responses r 
    JOIN questions q ON r.question_id = q.id 
    WHERE r.interview_id = ? 
    ORDER BY r.id ASC
    """, (interview_id,))
    rows = cursor.fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        if d.get("feedback_json"):
            try:
                d["feedback"] = json.loads(d["feedback_json"])
            except Exception:
                d["feedback"] = {}
        res.append(d)
    return res

# Report helpers
def save_report(interview_id: int, overall_score: int, content_score: int,
                technical_score: int, communication_score: int, problem_solving_score: int,
                scoring_engine: str, strengths: List[str], weaknesses: List[str],
                recommendations: List[str], practice_exercises: List[str],
                model_answers: List[Dict[str, Any]], presentation_obs: Dict[str, Any],
                overall_feedback: str) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT OR REPLACE INTO reports (interview_id, overall_score, content_score, technical_score,
                                    communication_score, problem_solving_score, scoring_engine,
                                    strengths_json, weaknesses_json, recommendations_json,
                                    practice_exercises_json, model_answers_json, presentation_obs_json,
                                    overall_feedback, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (interview_id, overall_score, content_score, technical_score,
          communication_score, problem_solving_score, scoring_engine,
          json.dumps(strengths), json.dumps(weaknesses), json.dumps(recommendations),
          json.dumps(practice_exercises), json.dumps(model_answers), json.dumps(presentation_obs),
          overall_feedback, now))
    cursor.execute("UPDATE interviews SET final_score = ?, score = ? WHERE id = ?", (overall_score, overall_score, interview_id))
    conn.commit()
    conn.close()
    return get_report_by_interview_id(interview_id)

def get_report_by_interview_id(interview_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE interview_id = ?", (interview_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["strengths"] = json.loads(d["strengths_json"] or "[]")
    d["weaknesses"] = json.loads(d["weaknesses_json"] or "[]")
    d["recommendations"] = json.loads(d["recommendations_json"] or "[]")
    d["practice_exercises"] = json.loads(d["practice_exercises_json"] or "[]")
    d["model_answers"] = json.loads(d["model_answers_json"] or "[]")
    d["presentation_observations"] = json.loads(d["presentation_obs_json"] or "{}")
    return d

# Settings helpers
def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
    """, (key, str(value), now))
    conn.commit()
    conn.close()

def get_all_settings() -> Dict[str, str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def get_configured_question_count(job_role: Optional[str] = None) -> int:
    if job_role:
        role_key = f"question_count_{job_role.lower().replace(' ', '_')}"
        role_val = get_setting(role_key)
        if role_val and role_val.isdigit():
            cnt = int(role_val)
            if 1 <= cnt <= 50:
                return cnt
    val = get_setting("default_question_count", "10")
    try:
        cnt = int(val)
        return max(1, min(50, cnt))
    except (ValueError, TypeError):
        return 10

# Initialize database schema on load
init_db()
