import sys
import time
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import init_db

def run_tests():
    print("=" * 60)
    print("RUNNING END-TO-END VIRTUAL AI INTERVIEW SIMULATOR TEST SUITE")
    print("=" * 60)
    init_db()
    client = TestClient(app)

    # 1. Test Health endpoint
    print("\n[TEST 1] Testing /api/health...")
    resp = client.get("/api/health")
    assert resp.status_code == 200, f"Health check failed: {resp.text}"
    health = resp.json()
    print(f"Health response: Provider={health.get('provider')} | Model={health.get('model')} | GeminiConfigured={health.get('gemini_configured')}")
    assert health["status"] == "healthy"

    # 2. Test Admin Login & Settings API
    print("\n[TEST 2] Testing Admin Login & Question Count Policy Settings...")
    admin_login_resp = client.post("/api/auth/admin-login", json={"email": "admin@demo.com", "password": "admin123"})
    assert admin_login_resp.status_code == 200, f"Admin login failed: {admin_login_resp.text}"
    admin_data = admin_login_resp.json()
    admin_headers = {"Authorization": f"Bearer {admin_data['token']}"}

    # Fetch initial settings
    get_settings_resp = client.get("/api/admin/settings", headers=admin_headers)
    assert get_settings_resp.status_code == 200
    initial_settings = get_settings_resp.json()
    print(f"Initial Admin Settings: {initial_settings}")
    assert initial_settings.get("default_question_count") in [10, "10", 3, 5]

    # Update default question count to 3
    set_settings_resp = client.post(
        "/api/admin/settings",
        json={"key": "default_question_count", "value": 3},
        headers=admin_headers
    )
    assert set_settings_resp.status_code == 200
    assert set_settings_resp.json()["default_question_count"] == 3
    print("Admin updated default_question_count to 3 successfully.")

    # Validate setting bounds (1-50): Reject 0 and 51
    bad_set1 = client.post("/api/admin/settings", json={"key": "default_question_count", "value": 0}, headers=admin_headers)
    assert bad_set1.status_code == 400
    bad_set2 = client.post("/api/admin/settings", json={"key": "default_question_count", "value": 51}, headers=admin_headers)
    assert bad_set2.status_code == 400
    print("Setting boundary validation (1–50) confirmed.")

    # 3. Candidate Registration and Auth
    print("\n[TEST 3] Testing Candidate Registration & Token Session...")
    test_email = f"candidate_adaptive_{int(time.time())}@example.com"
    reg_resp = client.post("/api/auth/register", json={
        "name": "Alex Mercer",
        "email": test_email,
        "password": "SecurePassword123"
    })
    assert reg_resp.status_code == 200, f"Registration failed: {reg_resp.text}"
    candidate_token = reg_resp.json()["token"]
    candidate_id = reg_resp.json()["user"]["id"]
    auth_headers = {"Authorization": f"Bearer {candidate_token}"}
    print(f"Registered Candidate: {test_email} (ID: {candidate_id})")

    # 4. Start Interview WITHOUT QuestionCount (Defaults to Admin Setting = 3)
    print("\n[TEST 4] Testing Default Question Count Inheritance (Candidate omits questionCount)...")
    create_resp = client.post("/api/interviews", json={
        "jobRole": "Backend Developer",
        "experienceLevel": "Senior",
        "interviewType": "Technical",
        "difficulty": "Hard",
        # questionCount intentionally omitted!
        "durationMinutes": 20,
        "cameraEnabled": True,
        "resumeText": "Senior Backend Engineer with expertise in PostgreSQL indexing, Redis caching, microservices decomposition, and distributed concurrency."
    }, headers=auth_headers)
    assert create_resp.status_code == 200, f"Interview creation failed: {create_resp.text}"
    create_data = create_resp.json()
    interview = create_data["interview"]
    interview_id = interview["id"]
    first_q = create_data["first_question"]
    print(f"Interview {interview_id} created with total questions: {interview['question_count']}")
    assert interview["question_count"] == 3, f"Expected 3 questions from admin setting, got {interview['question_count']}"
    print(f"Q1 Generated: '{first_q['question_text']}' [Topic: {first_q.get('topic')}]")
    assert first_q["question_text"]

    # 5. Answer Question 1 & Test Duplicate Submission Guard
    print("\n[TEST 5] Answering Q1 & Testing Adaptive Follow-Up Generation...")
    q1_answer = (
        "In our core transaction engine, we solved read/write contention on PostgreSQL by introducing "
        "read replicas for reporting and an asynchronous Kafka queue with an outbox pattern for distributed ledger writes. "
        "We also applied compound B-Tree indexes on tenant_id and created_at."
    )
    ans1_resp = client.post(
        f"/api/interviews/{interview_id}/responses",
        data={
            "question_id": first_q["id"],
            "response_duration": "48.5",
            "transcript": q1_answer,
            "framing_telemetry": '{"is_centered": true, "lighting": "Good"}'
        },
        headers=auth_headers
    )
    assert ans1_resp.status_code == 200, f"Submitting answer 1 failed: {ans1_resp.text}"
    ans1_data = ans1_resp.json()
    assert not ans1_data["interview_completed"]
    q2 = ans1_data["next_question"]
    assert q2 is not None
    print(f"Q1 Evaluated: Technical Score={ans1_data['analysis']['technical_score']}, Content={ans1_data['analysis']['content_score']}")
    print(f"Q1 Feedback Strengths: {ans1_data['feedback'].get('strengths', [])[:2]}")
    print(f"Adaptive Q2 Generated: '{q2['question_text']}'")

    # Duplicate submission guard test: submitting the same question again should be handled idempotently
    print("\n[TEST 5b] Testing Duplicate Submission Guard (User double-clicks Submit)...")
    ans1_dup = client.post(
        f"/api/interviews/{interview_id}/responses",
        data={
            "question_id": first_q["id"],
            "response_duration": "48.5",
            "transcript": q1_answer,
            "framing_telemetry": '{"is_centered": true, "lighting": "Good"}'
        },
        headers=auth_headers
    )
    assert ans1_dup.status_code == 200, f"Duplicate submit failed: {ans1_dup.text}"
    dup_data = ans1_dup.json()
    assert dup_data["answered_count"] == 1, "Duplicate response must not increase answered count!"
    print("Duplicate submission guard verified: Handled safely without corrupting interview progress.")

    # 6. Admin changes setting to 10 while this interview is in progress
    print("\n[TEST 6] Admin Changes Setting while Interview is In-Progress...")
    client.post("/api/admin/settings", json={"key": "default_question_count", "value": 10}, headers=admin_headers)
    # Check that in-progress interview keeps its original 3 questions
    curr_int = client.get(f"/api/interviews/{interview_id}", headers=auth_headers).json()["interview"]
    assert curr_int["question_count"] == 3, "In-progress interview count must remain immutable!"
    print("Immutability of in-progress interview question count verified.")

    # 7. Answer Question 2
    print("\n[TEST 7] Answering Q2 with Specific Technical Claims...")
    q2_answer = (
        "To ensure zero data loss during high load with Kafka, we set acks=all on producers, "
        "min.insync.replicas=2, and enabled idempotence. In consumers, we committed offsets only after "
        "the local transactional outbox insert committed successfully to the database."
    )
    ans2_resp = client.post(
        f"/api/interviews/{interview_id}/responses",
        data={
            "question_id": q2["id"],
            "response_duration": "55.0",
            "transcript": q2_answer,
            "framing_telemetry": '{"is_centered": true, "lighting": "Good"}'
        },
        headers=auth_headers
    )
    assert ans2_resp.status_code == 200
    ans2_data = ans2_resp.json()
    assert not ans2_data["interview_completed"]
    q3 = ans2_data["next_question"]
    assert q3 is not None
    print(f"Q2 Evaluated: Technical Score={ans2_data['analysis']['technical_score']}")
    print(f"Adaptive Q3 Generated: '{q3['question_text']}'")

    # 8. Answer Question 3 (Final Question) -> Triggers Completion
    print("\n[TEST 8] Answering Q3 (Final Question) -> Completes Interview...")
    q3_answer = (
        "When handling network partitions or broker degradation, our services fall back to local disk-backed "
        "buffering with circuit breakers and alerting to Prometheus/Grafana before gracefully degrading non-critical features."
    )
    ans3_resp = client.post(
        f"/api/interviews/{interview_id}/responses",
        data={
            "question_id": q3["id"],
            "response_duration": "40.0",
            "transcript": q3_answer,
            "framing_telemetry": '{"is_centered": true, "lighting": "Good"}'
        },
        headers=auth_headers
    )
    assert ans3_resp.status_code == 200
    ans3_data = ans3_resp.json()
    assert ans3_data["interview_completed"] is True, "Interview should be marked completed after Q3!"
    assert ans3_data["answered_count"] == 3
    print("Interview completed flag confirmed after answering all configured questions.")

    # 9. Test Final Report Generation
    print("\n[TEST 9] Testing Comprehensive Final Feedback Report Generation...")
    report_resp = client.get(f"/api/interviews/{interview_id}/report", headers=auth_headers)
    assert report_resp.status_code == 200, f"Report retrieval failed: {report_resp.text}"
    report_json = report_resp.json()
    report = report_json["report"]
    print(f"Report Overall Score: {report['overall_score']}/100")
    print(f"Technical Score: {report['technical_score']}/100")
    print(f"Communication Score: {report['communication_score']}/100")
    print(f"Scoring Engine: {report['scoring_engine']}")
    print(f"Strengths ({len(report['strengths'])}): {report['strengths'][:2]}")
    print(f"Recommendations ({len(report['recommendations'])}): {report['recommendations'][:2]}")
    print(f"Model Answers Generated: {len(report['model_answers'])}")
    assert report["overall_score"] > 0
    assert len(report["strengths"]) > 0
    assert len(report["weaknesses"]) > 0
    assert len(report["recommendations"]) > 0
    assert len(report["model_answers"]) >= 3
    assert report["overall_feedback"]

    # 10. Test Admin Scheduled Interview with Custom Question Count (e.g. 5)
    print("\n[TEST 10] Testing Admin Scheduled Interview with Custom Question Count...")
    sched_resp = client.post("/api/admin/schedule", json={
        "candidateId": candidate_id,
        "jobRole": "Frontend Developer",
        "interviewType": "Technical",
        "difficulty": "Medium",
        "questionCount": 5,
        "scheduledDate": "2026-11-01",
        "scheduledTime": "14:00"
    }, headers=admin_headers)
    assert sched_resp.status_code == 200, f"Scheduling failed: {sched_resp.text}"
    sched_data = sched_resp.json()
    sched_id = sched_data["interview"]["id"]
    print(f"Scheduled Interview ID: {sched_id} with configured question count: {sched_data['interview']['question_count']}")
    assert sched_data["interview"]["question_count"] == 5

    # Candidate sees scheduled interview on dashboard
    cand_dash = client.get("/api/candidate/dashboard", headers=auth_headers).json()
    upcoming_ids = [u["id"] for u in cand_dash.get("upcoming", [])]
    assert sched_id in upcoming_ids, "Candidate dashboard should list the scheduled interview."
    print("Candidate dashboard lists scheduled session correctly.")

    # =========================================================================
    # COMPREHENSIVE TESTS FOR SCHEDULED CANDIDATE INTERVIEW ACCESS & LIFECYCLE
    # =========================================================================
    from backend.app.routers.auth import sign_session_id
    from backend.app.database import get_user_by_id

    # 11. Test Registered Candidate (Prathiksha H M, user_id=6)
    print("\n[TEST 11] Verifying Registered Candidate Account (Prathiksha H M)...")
    prathiksha = get_user_by_id(6)
    assert prathiksha is not None, "Registered candidate Prathiksha H M (user_id=6) must exist in DB!"
    print(f"Registered candidate verified: ID={prathiksha['id']}, Name={prathiksha['name']}, Email={prathiksha['email']}")
    prathiksha_token = sign_session_id(prathiksha["id"])
    prathiksha_headers = {"Authorization": f"Bearer {prathiksha_token}"}

    # 12. Admin schedules an interview specifically for Prathiksha H M
    print("\n[TEST 12] Admin Schedules Interview for Prathiksha H M (2 Questions)...")
    admin_sched_resp = client.post("/api/admin/schedule", json={
        "candidateId": prathiksha["id"],
        "jobRole": "Full Stack AI Engineer",
        "interviewType": "Technical",
        "difficulty": "Medium",
        "questionCount": 2,
        "scheduledDate": "2026-11-05",
        "scheduledTime": "10:30"
    }, headers=admin_headers)
    assert admin_sched_resp.status_code == 200, f"Failed to schedule interview for Prathiksha: {admin_sched_resp.text}"
    p_interview = admin_sched_resp.json()["interview"]
    p_int_id = p_interview["id"]
    print(f"Scheduled Interview Created: ID={p_int_id}, Candidate={p_interview['candidate_id']}, Status={p_interview['status']}")
    assert p_interview["status"] == "scheduled"
    assert p_interview["candidate_id"] == prathiksha["id"]
    assert p_interview["question_count"] == 2

    # 13. Test Scenario 2: Before Interview Starts (Status is 'scheduled', no report, no score 0)
    print("\n[TEST 13] Scenario 2: Before Interview Starts...")
    p_dash = client.get("/api/candidate/dashboard", headers=prathiksha_headers).json()
    p_upcoming = [u for u in p_dash.get("upcoming", []) if u["id"] == p_int_id]
    assert len(p_upcoming) == 1, "Interview must appear in Prathiksha's upcoming list"
    assert p_upcoming[0]["status"] == "scheduled"
    print(f"Candidate dashboard displays interview as '{p_upcoming[0]['status']}'.")

    # Verify that requesting a report BEFORE interview starts returns 400 (NOT score 0)
    rep_before = client.get(f"/api/interviews/{p_int_id}/report", headers=prathiksha_headers)
    assert rep_before.status_code == 400, "Report must NOT be accessible before interview is completed"
    print("Pre-start report guard verified: 400 Bad Request returned, no fake score 0 generated.")

    # Verify that trying to finish an empty interview returns 400 and does NOT complete it
    finish_empty = client.post(f"/api/interviews/{p_int_id}/finish", headers=prathiksha_headers)
    assert finish_empty.status_code == 400, "Finishing an empty interview must be rejected with 400"
    print("Empty interview finish guard verified: 400 Bad Request returned, interview cannot be prematurely completed.")

    # 14. Test Scenario 5: Unauthorized Access (Candidate A cannot start or view Candidate B's interview)
    print("\n[TEST 14] Scenario 5: Testing Unauthorized Access Protection (403 Forbidden)...")
    # Alex Mercer tries to access Prathiksha's interview
    unauth_get = client.get(f"/api/interviews/{p_int_id}", headers=auth_headers)
    assert unauth_get.status_code == 403, f"Expected 403 for unauthorized GET, got {unauth_get.status_code}"

    unauth_start = client.post(f"/api/interviews/{p_int_id}/start", headers=auth_headers)
    assert unauth_start.status_code == 403, f"Expected 403 for unauthorized start, got {unauth_start.status_code}"

    unauth_ans = client.post(
        f"/api/interviews/{p_int_id}/responses",
        data={"question_id": 1, "transcript": "hacked answer"},
        headers=auth_headers
    )
    assert unauth_ans.status_code == 403, f"Expected 403 for unauthorized response submit, got {unauth_ans.status_code}"
    print("Unauthorized access protection verified: 403 Forbidden returned for all unauthorized operations.")

    # 15. Test Scenario 1 & 3: Prathiksha Clicks 'Start Interview'
    print("\n[TEST 15] Scenario 1 & 3: Prathiksha Clicks 'Start Interview'...")
    start_resp = client.post(f"/api/interviews/{p_int_id}/start", headers=prathiksha_headers)
    assert start_resp.status_code == 200, f"Start interview failed: {start_resp.text}"
    start_data = start_resp.json()
    assert start_data["interview"]["status"] == "in_progress", "Interview status must be 'in_progress' after starting!"
    assert start_data["first_question"] is not None, "First question must be generated and returned!"
    p_q1 = start_data["first_question"]
    print(f"Interview {p_int_id} started! Status: {start_data['interview']['status']}")
    print(f"First Question Generated: '{p_q1['question_text']}'")
    assert p_q1["question_text"] == "Please introduce yourself.", f"Expected 'Please introduce yourself.', got '{p_q1['question_text']}'"

    # Verify interview room GET also returns in_progress and current question without completing
    room_resp = client.get(f"/api/interviews/{p_int_id}", headers=prathiksha_headers)
    assert room_resp.status_code == 200
    room_data = room_resp.json()
    assert room_data["interview"]["status"] == "in_progress"
    assert room_data["current_question"]["id"] == p_q1["id"]
    print("Interview room load verified: in_progress status maintained, Q1 loaded.")

    # 16. Candidate answers Question 1
    print("\n[TEST 16] Prathiksha Answers Question 1...")
    p_ans1 = (
        "In modern full-stack web applications, I design modular REST and WebSocket APIs using FastAPI, "
        "manage reactive UI state with vanilla JS or React, and implement resilient background workers "
        "with Celery or Redis queues to process heavy AI evaluation tasks asynchronously."
    )
    p_ans1_resp = client.post(
        f"/api/interviews/{p_int_id}/responses",
        data={
            "question_id": p_q1["id"],
            "response_duration": "42.0",
            "transcript": p_ans1,
            "framing_telemetry": '{"is_centered": true, "lighting": "Good"}'
        },
        headers=prathiksha_headers
    )
    assert p_ans1_resp.status_code == 200, f"Failed to submit Q1 answer: {p_ans1_resp.text}"
    p_ans1_data = p_ans1_resp.json()
    assert not p_ans1_data["interview_completed"]
    assert p_ans1_data["answered_count"] == 1
    p_q2 = p_ans1_data["next_question"]
    assert p_q2 is not None
    print(f"Q1 Answered and Analyzed. Adaptive Q2 Generated: '{p_q2['question_text']}'")

    # 17. Test Scenario 6: Refresh and Resume during interview
    print("\n[TEST 17] Scenario 6: Testing Refresh and Resume mid-interview...")
    resume_resp = client.get(f"/api/interviews/{p_int_id}", headers=prathiksha_headers)
    assert resume_resp.status_code == 200
    resume_data = resume_resp.json()
    assert resume_data["interview"]["status"] == "in_progress", "Interview must remain in_progress after refresh"
    assert len(resume_data["responses"]) == 1, "Previously submitted response must be preserved"
    assert resume_data["current_question"]["id"] == p_q2["id"], "Current question must point to Q2"
    print("Refresh and resume verified: State preserved, no duplicate questions, not prematurely completed.")

    # 18. Candidate answers Question 2 (Final question) -> Completes Interview
    print("\n[TEST 18] Prathiksha Answers Final Question 2 -> Completes Interview...")
    p_ans2 = (
        "To ensure robust AI prompt engineering and prevent hallucinations, I use strict JSON schema validation, "
        "few-shot domain examples in system prompts, temperature controls, and deterministic fallback heuristics "
        "whenever the model output violates schema contracts."
    )
    p_ans2_resp = client.post(
        f"/api/interviews/{p_int_id}/responses",
        data={
            "question_id": p_q2["id"],
            "response_duration": "45.0",
            "transcript": p_ans2,
            "framing_telemetry": '{"is_centered": true, "lighting": "Good"}'
        },
        headers=prathiksha_headers
    )
    assert p_ans2_resp.status_code == 200
    p_ans2_data = p_ans2_resp.json()
    assert p_ans2_data["interview_completed"] is True
    assert p_ans2_data["answered_count"] == 2
    print("Interview completion confirmed after answering all configured questions.")

    # 19. Test Scenario 4: After Completion (Status is 'completed', real report with real score)
    print("\n[TEST 19] Scenario 4: Verifying Final Evaluation & Real Score Calculation...")
    p_report_resp = client.get(f"/api/interviews/{p_int_id}/report", headers=prathiksha_headers)
    assert p_report_resp.status_code == 200, f"Report retrieval failed: {p_report_resp.text}"
    p_rep = p_report_resp.json()["report"]
    print(f"Final Report Overall Score: {p_rep['overall_score']}/100")
    print(f"Technical Score: {p_rep['technical_score']}/100")
    print(f"Communication Score: {p_rep['communication_score']}/100")
    assert p_rep["overall_score"] > 0, "Completed interview must have a calculated score > 0!"
    assert len(p_rep["strengths"]) > 0
    assert len(p_rep["weaknesses"]) > 0
    assert len(p_rep["recommendations"]) > 0
    assert len(p_rep["model_answers"]) == 2

    # Check candidate history
    hist_resp = client.get("/api/candidate/history", headers=prathiksha_headers)
    assert hist_resp.status_code == 200
    p_history = hist_resp.json()["history"]
    matched_hist = [h for h in p_history if h["id"] == p_int_id]
    assert len(matched_hist) == 1
    assert matched_hist[0]["status"] == "completed"
    score_val = matched_hist[0].get("overall_score") or (matched_hist[0].get("report") and matched_hist[0]["report"]["overall_score"])
    assert score_val == p_rep["overall_score"]
    print(f"Candidate history accurately records completed interview with score {score_val}.")

    # 20. Test Cancelled & Missed Interview Status Transitions
    print("\n[TEST 20] Testing Cancelled and Missed Status Workflows...")
    # Schedule another interview for cancellation test
    cancel_sched = client.post("/api/admin/schedule", json={
        "candidateId": prathiksha["id"],
        "jobRole": "DevOps Engineer",
        "interviewType": "Technical",
        "difficulty": "Medium",
        "questionCount": 3,
        "scheduledDate": "2026-11-10",
        "scheduledTime": "11:00"
    }, headers=admin_headers).json()["interview"]
    cancel_id = cancel_sched["id"]

    # Admin cancels it
    cancel_act = client.post(f"/api/admin/cancel/{cancel_id}", headers=admin_headers)
    assert cancel_act.status_code == 200
    print(f"Interview {cancel_id} cancelled by admin.")

    # Candidate tries to start cancelled interview -> Rejected with 400
    start_cancelled = client.post(f"/api/interviews/{cancel_id}/start", headers=prathiksha_headers)
    assert start_cancelled.status_code == 400
    assert "cancelled" in start_cancelled.text.lower()
    print("Starting cancelled interview rejected with 400 Bad Request.")

    # Schedule another interview for missed test
    missed_sched = client.post("/api/admin/schedule", json={
        "candidateId": prathiksha["id"],
        "jobRole": "QA Engineer",
        "interviewType": "Technical",
        "difficulty": "Medium",
        "questionCount": 3,
        "scheduledDate": "2026-10-01",
        "scheduledTime": "09:00"
    }, headers=admin_headers).json()["interview"]
    missed_id = missed_sched["id"]

    # Mark as missed
    missed_act = client.post(f"/api/admin/missed/{missed_id}", headers=admin_headers)
    assert missed_act.status_code == 200
    print(f"Interview {missed_id} marked as missed.")

    # Candidate tries to start missed interview -> Rejected with 400
    start_missed = client.post(f"/api/interviews/{missed_id}/start", headers=prathiksha_headers)
    assert start_missed.status_code == 400
    assert "missed" in start_missed.text.lower()
    print("Starting missed interview rejected with 400 Bad Request.")

    # 21. Test Candidate ID Validation on Interview Scheduling (Requirement 6)
    print("\n[TEST 21] Testing Candidate ID Validation on Scheduling...")
    # Scheduling with a non-existent candidate ID should be rejected with 400
    bad_cand_resp = client.post("/api/admin/schedule", json={
        "candidateId": 99999,
        "jobRole": "Full Stack Engineer",
        "interviewType": "Technical",
        "difficulty": "Medium",
        "questionCount": 3,
        "scheduledDate": "2026-11-20",
        "scheduledTime": "15:00"
    }, headers=admin_headers)
    assert bad_cand_resp.status_code == 400, f"Expected 400 for non-existent candidate ID, got {bad_cand_resp.status_code}"

    # Scheduling with an admin ID (ID 1) should be rejected with 400
    admin_cand_resp = client.post("/api/admin/schedule", json={
        "candidateId": 1,
        "jobRole": "Full Stack Engineer",
        "interviewType": "Technical",
        "difficulty": "Medium",
        "questionCount": 3,
        "scheduledDate": "2026-11-20",
        "scheduledTime": "15:00"
    }, headers=admin_headers)
    assert admin_cand_resp.status_code == 400, f"Expected 400 for admin ID as candidate, got {admin_cand_resp.status_code}"
    print("Candidate ID validation verified: Only genuine registered job seekers can be scheduled.")

    # 22. Teardown: Clean up temporary test candidate and verify ONLY Prathiksha H M remains
    print("\n[TEST 22] Teardown Temporary Test Candidate & Verify Only Genuine Registered Candidates Remain...")
    from backend.app.database import delete_user_and_data, get_all_candidates
    delete_user_and_data(candidate_id)
    print(f"Temporary test candidate (ID {candidate_id}) cleanly deleted.")

    # Verify admin candidate list
    admin_cands = client.get("/api/admin/candidates", headers=admin_headers).json()["candidates"]
    assert len(admin_cands) == 1, f"Expected exactly 1 registered candidate, found {len(admin_cands)}"
    assert admin_cands[0]["id"] == 6
    assert admin_cands[0]["name"] == "Prathiksha H M"
    assert admin_cands[0]["email"] == "pratikshahm1506@gmail.com"
    print("Admin candidate listing verified: Only Prathiksha H M is present.")

    # Verify admin dashboard stats
    admin_dash = client.get("/api/admin/dashboard", headers=admin_headers).json()
    assert admin_dash["stats"]["seekers_count"] == 1
    cand_names = [c["name"] for c in admin_dash["candidates"]]
    assert cand_names == ["Prathiksha H M"]
    print("Admin dashboard stats and directory verified: 100% genuine candidate purity.")

    # Verify Prathiksha can still log in and view her dashboard
    prathiksha_dash = client.get("/api/candidate/dashboard", headers=prathiksha_headers).json()
    assert prathiksha_dash["user"]["name"] == "Prathiksha H M"
    assert prathiksha_dash["user"]["email"] == "pratikshahm1506@gmail.com"
    print("Prathiksha H M dashboard fully accessible.")

    # 23. Test Requirement 1: Separate Interview Details & Q&A Inspection for Admin
    print("\n[TEST 23] Testing Admin Interview Details Endpoint (Questions, Answers, Scores)...")
    details_resp = client.get(f"/api/admin/interviews/{p_int_id}/details", headers=admin_headers)
    assert details_resp.status_code == 200
    details = details_resp.json()
    assert details["interview"]["id"] == p_int_id
    assert details["candidate"]["name"] == "Prathiksha H M"
    assert len(details["questions"]) == 2
    assert len(details["responses"]) == 2
    assert details["report"] is not None
    assert details["report"]["overall_score"] > 0
    print("Admin interview details verified: Returns full questions, transcripts, and scores.")

    # 24. Test Requirement 1: Safe Deletion of an Interview Record without Deleting Candidate Account
    print("\n[TEST 24] Testing Safe Single Interview Deletion (Candidate Account Preserved)...")
    del_resp = client.delete(f"/api/admin/interviews/{p_int_id}", headers=admin_headers)
    assert del_resp.status_code == 200
    # Candidate must STILL exist!
    p_check = get_user_by_id(prathiksha["id"])
    assert p_check is not None
    assert p_check["name"] == "Prathiksha H M"
    print("Safe single interview deletion verified: Interview deleted, candidate account safely preserved.")

    # 25. Test Requirement 1: Safe Clear All Interview History without Deleting Candidate Account
    print("\n[TEST 25] Testing Clear All Interview History (Candidate Account Preserved)...")
    clear_resp = client.delete("/api/admin/interview-history", headers=admin_headers)
    assert clear_resp.status_code == 200
    interviews_after = client.get("/api/admin/dashboard", headers=admin_headers).json()["interviews"]
    assert len(interviews_after) == 0
    p_check2 = get_user_by_id(prathiksha["id"])
    assert p_check2 is not None
    assert p_check2["name"] == "Prathiksha H M"
    print("Clear all interview history verified: 0 interviews remain, candidate account preserved.")

    # 26. Test Requirement 4 & 5: Fresh Scheduled Interview Without Resume
    # Question 1 MUST be "Please introduce yourself."
    print("\n[TEST 26] Testing Interview Without Resume -> Q1 Must Be 'Please introduce yourself.'...")
    sched_no_resume = client.post("/api/admin/schedule", json={
        "candidateId": prathiksha["id"],
        "jobRole": "Frontend Developer",
        "interviewType": "Technical",
        "difficulty": "Easy",
        "questionCount": 3,
        "scheduledDate": "2026-11-15",
        "scheduledTime": "14:00"
    }, headers=admin_headers).json()["interview"]
    no_resume_id = sched_no_resume["id"]

    start_no_res = client.post(f"/api/interviews/{no_resume_id}/start", headers=prathiksha_headers)
    assert start_no_res.status_code == 200
    q1_no_res = start_no_res.json()["first_question"]
    assert q1_no_res["question_text"] == "Please introduce yourself.", f"Expected 'Please introduce yourself.', got '{q1_no_res['question_text']}'"
    print(f"Q1 without resume confirmed: '{q1_no_res['question_text']}'")

    # Submit introduction
    intro_resp = client.post(
        f"/api/interviews/{no_resume_id}/responses",
        data={
            "question_id": q1_no_res["id"],
            "response_duration": "35.0",
            "transcript": "Hello, I am a frontend developer with 2 years of experience using React, TypeScript, and Tailwind CSS. I have built user interfaces and dashboards for analytics.",
            "framing_telemetry": '{"is_centered": true, "lighting": "Good"}'
        },
        headers=prathiksha_headers
    )
    assert intro_resp.status_code == 200
    intro_data = intro_resp.json()
    q2_adaptive = intro_data["next_question"]
    assert q2_adaptive is not None
    print(f"Adaptive Q2 after introduction: '{q2_adaptive['question_text']}'")
    assert len(q2_adaptive["question_text"]) > 10

    # 27. Test Requirement 4: Mark Not Attended Workflow
    print("\n[TEST 27] Testing Not Attended Status Endpoint...")
    sched_na = client.post("/api/admin/schedule", json={
        "candidateId": prathiksha["id"],
        "jobRole": "Software Developer",
        "interviewType": "Technical",
        "difficulty": "Medium",
        "questionCount": 3,
        "scheduledDate": "2026-10-10",
        "scheduledTime": "09:00"
    }, headers=admin_headers).json()["interview"]
    na_id = sched_na["id"]

    na_act = client.post(f"/api/admin/not-attended/{na_id}", headers=admin_headers)
    assert na_act.status_code == 200
    na_int = client.get(f"/api/interviews/{na_id}", headers=admin_headers).json()["interview"]
    assert na_int["status"] == "not_attended"
    print("Not Attended status correctly assigned and preserved.")

    # 28. Test Requirement 2: Confidential Admin Login
    print("\n[TEST 28] Testing Admin Login Confidentiality...")
    adm_login = client.post("/api/auth/admin-login", json={"email": "admin@demo.com", "password": "admin123"})
    assert adm_login.status_code == 200
    adm_user = adm_login.json()["user"]
    assert "password" not in adm_user
    assert "password_hash" not in adm_user
    print("Admin credentials authenticated securely; no password or sensitive hash exposed.")

    # 29. Test Multi-Turn Adaptive Question Generation Chain
    print("\n[TEST 29] Testing Multi-Turn Adaptive Question Generation Chain (Q1 -> A1 -> Q2 -> A2 -> Q3 -> A3 -> Q4)...")
    # Fresh interview for Prathiksha without resume
    adaptive_int = client.post("/api/interviews", json={
        "jobRole": "Software Developer",
        "experienceLevel": "Entry-Level",
        "interviewType": "Technical",
        "difficulty": "Medium",
        "questionCount": 5,
        "durationMinutes": 25,
        "cameraEnabled": False,
        "resumeText": ""  # No resume!
    }, headers=prathiksha_headers).json()

    a_int_id = adaptive_int["interview"]["id"]
    q1 = adaptive_int["first_question"]
    print(f"Turn 1 Question: '{q1['question_text']}'")
    assert q1["question_text"] == "Please introduce yourself.", f"Expected 'Please introduce yourself.', got '{q1['question_text']}'"

    # Turn 1: Candidate introduces themselves mentioning Python, SQL, and ML project
    a1_text = "I am a Computer Science student. I know Python and SQL, and I have worked on a machine learning project."
    resp1 = client.post(f"/api/interviews/{a_int_id}/responses", data={
        "question_id": q1["id"],
        "response_duration": "25.0",
        "transcript": a1_text
    }, headers=prathiksha_headers)
    assert resp1.status_code == 200
    q2_data = resp1.json()["next_question"]
    assert q2_data is not None
    q2_text = q2_data["question_text"]
    print(f"Turn 2 Adaptive Question: '{q2_text}'")
    # Must mention machine learning, project, or Python
    q2_lower = q2_text.lower()
    assert any(term in q2_lower for term in ["machine learning", "project", "python", "sql", "computer science"]), \
        f"Q2 must be based on Answer 1, got: {q2_text}"

    # Turn 2: Candidate answers about linear regression and machine output
    a2_text = "I used Python and linear regression to predict machine output."
    resp2 = client.post(f"/api/interviews/{a_int_id}/responses", data={
        "question_id": q2_data["id"],
        "response_duration": "20.0",
        "transcript": a2_text
    }, headers=prathiksha_headers)
    assert resp2.status_code == 200
    q3_data = resp2.json()["next_question"]
    assert q3_data is not None
    q3_text = q3_data["question_text"]
    print(f"Turn 3 Adaptive Question: '{q3_text}'")
    # Must mention linear regression, output, prediction, or model evaluation
    q3_lower = q3_text.lower()
    assert any(term in q3_lower for term in ["linear regression", "predict", "output", "machine", "model", "evaluate"]), \
        f"Q3 must be based on Answer 2, got: {q3_text}"
    assert q3_text != q2_text, "Questions must not repeat!"

    # Turn 3: Candidate answers about MSE and R-squared on train-test split
    a3_text = "I evaluated the model using Mean Squared Error and R-squared on an 80-20 train-test split."
    resp3 = client.post(f"/api/interviews/{a_int_id}/responses", data={
        "question_id": q3_data["id"],
        "response_duration": "22.0",
        "transcript": a3_text
    }, headers=prathiksha_headers)
    assert resp3.status_code == 200
    q4_data = resp3.json()["next_question"]
    assert q4_data is not None
    q4_text = q4_data["question_text"]
    print(f"Turn 4 Adaptive Question: '{q4_text}'")
    # Must mention evaluation metrics, MSE, R-squared, train-test split, or overfitting
    q4_lower = q4_text.lower()
    assert any(term in q4_lower for term in ["squared", "r-squared", "mse", "split", "train", "test", "evaluat", "overfitting", "metric", "model", "feature", "cross"]), \
        f"Q4 must be based on Answer 3, got: {q4_text}"
    assert q4_text not in [q1["question_text"], q2_text, q3_text], "Questions must not repeat!"
    print("Multi-turn adaptive question generation chain verified successfully!")

    # 30. Test First Question WITH Resume (Must NOT be 'Please introduce yourself.')
    print("\n[TEST 30] Testing First Question WITH Resume (Tailored to resume highlights)...")
    resume_int = client.post("/api/interviews", json={
        "jobRole": "Software Developer",
        "experienceLevel": "Senior",
        "interviewType": "Technical",
        "difficulty": "Hard",
        "questionCount": 3,
        "durationMinutes": 15,
        "cameraEnabled": False,
        "resumeText": "Experienced Backend Developer specializing in distributed systems, FastAPI, PostgreSQL, and high-throughput Kafka event streaming."
    }, headers=prathiksha_headers).json()

    q1_resume = resume_int["first_question"]
    print(f"Resume Q1: '{q1_resume['question_text']}'")
    assert q1_resume["question_text"] != "Please introduce yourself.", "With resume, Q1 must be tailored, not 'Please introduce yourself.'"
    q1_res_lower = q1_resume["question_text"].lower()
    assert any(term in q1_res_lower for term in ["fastapi", "postgresql", "kafka", "distributed", "backend", "project", "experience", "system"]), \
        f"Resume Q1 must reflect resume skills, got: {q1_resume['question_text']}"
    print("Resume-tailored first question verified successfully!")

    # Clear test interviews to leave system with no old history
    from backend.app.database import clear_all_interview_history
    clear_all_interview_history()
    print("System clean state preserved.")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    run_tests()
