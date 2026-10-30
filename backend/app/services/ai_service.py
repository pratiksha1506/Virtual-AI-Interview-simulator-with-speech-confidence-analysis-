import json
import logging
import random
import re
from typing import List, Dict, Any, Optional
import httpx
from ..config import GEMINI_API_KEY, OPENAI_API_KEY, LLM_MODEL

logger = logging.getLogger("ai_service")

# Static role question bank for intelligent local fallback & grounding.
# All questions are crafted to be simple, clear, professional, grammatically correct,
# and ask strictly ONE question at a time.
ROLE_QUESTION_BANKS = {
    "Software Developer": {
        "Technical": [
            {
                "topic": "Data Structures",
                "question": "What are the main differences between an array and a linked list, and when would you choose one over the other?",
                "expected": "array contiguous memory cache locality o1 lookup linked list pointers insertion deletion o1 at head"
            },
            {
                "topic": "API Design",
                "question": "What are the key principles of a RESTful API, and how do you design endpoints for scalability?",
                "expected": "stateless resource url http verbs over-fetching under-fetching client server caching graphql payload"
            },
            {
                "topic": "Databases & Transactions",
                "question": "Can you explain ACID properties in relational databases and why they are important for data consistency?",
                "expected": "atomicity consistency isolation durability transactions connection pool limit socket leak concurrency"
            },
            {
                "topic": "Asynchronous Programming",
                "question": "How does the JavaScript event loop process asynchronous tasks and promises?",
                "expected": "call stack event loop task queue microtask promise macrotask requestanimationframe non-blocking"
            }
        ],
        "Behavioral": [
            {
                "topic": "Problem Solving",
                "question": "Can you tell me about a challenging bug you diagnosed and resolved in a production environment?",
                "expected": "logs monitoring metrics reproduction race condition root cause postmortem regression testing"
            },
            {
                "topic": "Team Collaboration",
                "question": "How do you handle a disagreement with a team member over a technical decision?",
                "expected": "respectful discussion benchmarks data trade-offs team alignment compromise objective criteria"
            }
        ],
        "Situational": [
            {
                "topic": "Production Incidents",
                "question": "If an application experiences sudden latency spikes after a deployment, what steps do you take to troubleshoot it?",
                "expected": "triage rollback incident communication investigate logs metrics isolate canary deployment fix"
            }
        ],
        "HR": [
            {
                "topic": "Career Goals",
                "question": "What motivated you to apply for this software developer role, and where do you see your technical career heading over the next few years?",
                "expected": "growth motivation impact technical depth mentorship engineering culture alignment"
            }
        ]
    },
    "Frontend Developer": {
        "Technical": [
            {
                "topic": "Web Performance",
                "question": "How do you optimize page load speed and improve Core Web Vitals on a web application?",
                "expected": "lcp cls fid inp image optimization lazy loading font-display cdn critical css aspect-ratio layout stability"
            },
            {
                "topic": "State Management",
                "question": "How do you decide between different state management approaches in a frontend application?",
                "expected": "re-renders boilerplate selectors unidirectional data flow server cache zustand recoil context performance"
            },
            {
                "topic": "Accessibility & Design",
                "question": "What techniques do you use to ensure your web pages are fully accessible and responsive across screen sizes?",
                "expected": "aria labels semantic html contrast ratio focus management screen readers rem units responsive design"
            }
        ],
        "Behavioral": [
            {
                "topic": "Design Collaboration",
                "question": "How do you collaborate with UI/UX designers when a proposed design creates performance or accessibility challenges?",
                "expected": "collaboration alternatives user experience frame rate aria fallback graceful degradation empathy"
            }
        ]
    },
    "Backend Developer": {
        "Technical": [
            {
                "topic": "Distributed Messaging",
                "question": "How do you ensure data consistency and prevent duplicate processing in message-driven systems?",
                "expected": "idempotency keys outbox pattern eventual consistency deduplication saga pattern dead letter queue"
            },
            {
                "topic": "Database Optimization",
                "question": "How do database indexes work internally, and how do you identify slow queries?",
                "expected": "b-tree index composite index table scan index seek query planner cardinality explain analyze"
            },
            {
                "topic": "API Security",
                "question": "How do you design a secure authentication and authorization flow using JWTs and refresh tokens?",
                "expected": "jwt refresh token rotation http-only cookie csrf cors rate limiting redis expiry salt bcrypt"
            }
        ],
        "Behavioral": [
            {
                "topic": "Technical Debt",
                "question": "Can you describe a time when you refactored an existing service while ensuring zero downtime?",
                "expected": "strangler fig pattern dual writing feature flags integration testing backward compatibility monitoring"
            }
        ]
    },
    "Data Analyst": {
        "Technical": [
            {
                "topic": "SQL & Queries",
                "question": "What is the difference between window functions and GROUP BY in SQL, and when would you use each?",
                "expected": "window functions partition by order by rank dense_rank group by collapse rows running totals"
            },
            {
                "topic": "Data Cleaning",
                "question": "When working with messy or incomplete datasets, what is your approach for data cleaning and validation?",
                "expected": "data cleaning mean median imputation z-score iqr deduplication domain knowledge sensitivity analysis"
            }
        ],
        "Behavioral": [
            {
                "topic": "Stakeholder Communication",
                "question": "Can you describe a situation where your data insights challenged stakeholder assumptions, and how you communicated the results?",
                "expected": "data storytelling visualizations clear charts business impact objective data confidence intervals"
            }
        ]
    },
    "HR Interview": {
        "HR": [
            {
                "topic": "Professional Background",
                "question": "Can you walk me through your professional background and what you consider your most significant accomplishment?",
                "expected": "career summary achievements passion collaboration values alignment impact"
            },
            {
                "topic": "Conflict Resolution",
                "question": "Can you describe a conflict or disagreement you experienced at work and how you worked to resolve it?",
                "expected": "active listening communication empathy common goals constructive mediation professionalism"
            },
            {
                "topic": "Continuous Improvement",
                "question": "What is one professional skill you focused on improving recently, and what progress have you made?",
                "expected": "self-awareness growth mindset feedback deliberate practice measurable progress maturity"
            }
        ],
        "Behavioral": [
            {
                "topic": "Prioritization",
                "question": "How do you prioritize your responsibilities when faced with competing deadlines from different stakeholders?",
                "expected": "prioritization eisenhower matrix stakeholder communication delegation transparency deliverables"
            }
        ]
    }
}

async def call_gemini(prompt: str, system_instruction: str = "", max_tokens: int = 3500) -> Optional[tuple[str, str]]:
    """
    Call Google Gemini API using httpx with automatic model fallback.
    Returns tuple (clean_json_text, model_name) or None.
    If 429 quota limit is encountered, exits immediately to avoid freezing.
    """
    if not GEMINI_API_KEY:
        return None

    candidate_models = []
    for m in [LLM_MODEL, "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-flash-latest"]:
        if m and m not in candidate_models:
            candidate_models.append(m)

    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json"
        }
    }
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    async with httpx.AsyncClient(timeout=10.0) as client:
        for model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            text = parts[0]["text"].strip()
                            if text.startswith("```json"):
                                text = text[7:]
                            elif text.startswith("```"):
                                text = text[3:]
                            if text.endswith("```"):
                                text = text[:-3]
                            return text.strip(), model
                elif resp.status_code == 429:
                    logger.warning(f"Gemini API ({model}) returned quota 429. Trying next available model...")
                    continue
                else:
                    logger.warning(f"Gemini API ({model}) returned status {resp.status_code}: {resp.text[:120]}")
            except Exception as e:
                logger.error(f"Gemini API call failed for {model}: {e}")
    return None

async def call_openai(messages: List[Dict[str, str]]) -> Optional[str]:
    """Call OpenAI API using httpx."""
    if not OPENAI_API_KEY:
        return None
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.6,
        "response_format": {"type": "json_object"}
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.warning(f"OpenAI API returned error {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        logger.error(f"OpenAI API call failed: {e}")
    return None

def extract_candidate_concepts(text: str) -> Dict[str, Any]:
    """
    Extracts technologies, algorithms, metrics, and domain action phrases from candidate's answer.
    """
    text_lower = text.lower()

    ml_models = [
        "linear regression", "logistic regression", "random forest", "decision tree",
        "gradient boosting", "xgboost", "lightgbm", "svm", "support vector machine",
        "k-means", "knn", "neural network", "deep learning", "cnn", "rnn", "lstm",
        "transformer", "llm", "bert", "gpt"
    ]
    matched_models = [m for m in ml_models if m in text_lower]

    metrics = [
        "mean squared error", "mse", "rmse", "r-squared", "r2", "mae",
        "accuracy", "precision", "recall", "f1-score", "f1 score", "auc-roc",
        "cross-validation", "cross validation", "train-test split", "train test split",
        "overfitting", "underfitting"
    ]
    matched_metrics = [m for m in metrics if m in text_lower]

    tech_skills = [
        "python", "sql", "postgresql", "mysql", "mongodb", "redis", "javascript",
        "typescript", "react", "angular", "vue", "fastapi", "django", "flask",
        "node", "express", "java", "spring boot", "c++", "c#", ".net", "docker",
        "kubernetes", "aws", "azure", "gcp", "git", "rest api", "graphql", "kafka",
        "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch"
    ]
    matched_tech = [t for t in tech_skills if re.search(r'\b' + re.escape(t) + r'\b', text_lower)]

    domains = [
        "machine learning", "data science", "data analysis", "web development",
        "backend", "frontend", "full stack", "cloud computing", "devops",
        "microservices", "predict machine output", "predicting machine output",
        "sentiment analysis", "recommendation system", "computer vision", "nlp"
    ]
    matched_domains = [d for d in domains if d in text_lower]

    # Extract project action if present (e.g. "to predict machine output", "built a web application")
    action_match = re.search(r'\b(?:to|for|in order to)\s+([a-z0-9\s]{5,35})(?:\.|\,|$|\sand\b)', text_lower)
    raw_action = action_match.group(1).strip() if action_match else None
    cleaned_action = None
    if raw_action:
        # Convert verb if needed (e.g. "predict machine output" -> "predicting machine output")
        parts = raw_action.split()
        if parts:
            first = parts[0]
            if first.endswith("e") and not first.endswith("ee"):
                parts[0] = first[:-1] + "ing"
            elif not first.endswith("ing"):
                parts[0] = first + "ing"
            cleaned_action = " ".join(parts)

    words = re.findall(r'\b\w+\b', text)

    return {
        "models": matched_models,
        "metrics": matched_metrics,
        "tech": matched_tech,
        "domains": matched_domains,
        "project_action": cleaned_action or ("predicting machine output" if "predict machine output" in text_lower else None),
        "word_count": len(words)
    }

def local_heuristic_question(job_role: str, experience_level: str, interview_type: str,
                             difficulty: str, sequence_num: int, resume_text: Optional[str] = None,
                             previous_qa: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Intelligent local heuristic question generator with context-awareness and adaptive follow-ups.
    Enforces clear, simple, professional questions, asking only one question at a time.
    Never relies on random unrelated question banks for follow-up turns.
    """
    has_resume = bool(resume_text and resume_text.strip())

    # Requirement 1 & 5: Without resume, Question 1 must be strictly "Please introduce yourself."
    if sequence_num == 1 and not has_resume:
        return {
            "question_text": "Please introduce yourself.",
            "question_type": "Introduction",
            "topic": "Self Introduction",
            "difficulty": difficulty,
            "expected_keywords": "background experience projects skills passion introduction",
            "context_notes": "Initial self-introduction question (interview without resume)"
        }

    # Requirement 1: With resume, Question 1 is tailored to resume highlights
    if sequence_num == 1 and has_resume:
        extracted = extract_candidate_concepts(resume_text)
        lead_tech = extracted["tech"][0].capitalize() if extracted["tech"] else "software development"
        lead_domain = extracted["domains"][0] if extracted["domains"] else job_role
        return {
            "question_text": f"Looking at your background in {lead_tech} and {lead_domain}, could you walk me through your key contributions on your most significant recent project?",
            "question_type": interview_type,
            "topic": "Resume Project Walkthrough",
            "difficulty": difficulty,
            "expected_keywords": f"{lead_tech} {lead_domain} architecture implementation ownership results",
            "context_notes": "[Tailored Resume Opening Question]"
        }

    # Turns 2+: Must be strictly based on candidate's previous response
    if not previous_qa or len(previous_qa) == 0:
        return {
            "question_text": "Please introduce yourself.",
            "question_type": "Introduction",
            "topic": "Self Introduction",
            "difficulty": difficulty,
            "expected_keywords": "background experience skills",
            "context_notes": "Fallback opening"
        }

    last_turn = previous_qa[-1]
    last_q = last_turn.get("question", "")
    last_a = last_turn.get("transcript", "").strip()
    asked_texts = [qa.get("question", "") for qa in previous_qa]

    extracted = extract_candidate_concepts(last_a)
    models = extracted["models"]
    metrics = extracted["metrics"]
    tech = extracted["tech"]
    domains = extracted["domains"]
    action = extracted["project_action"]
    words = extracted["word_count"]

    # Check previously asked questions to prevent repetition
    covered_text = " ".join(asked_texts).lower()

    # Case 1: Candidate answered Question 1 (Introduction)
    is_q1_intro = "introduce" in last_q.lower() or sequence_num == 2
    if is_q1_intro:
        if models or domains:
            domain_name = models[0] if models else domains[0]
            tools = [t for t in tech if t not in domain_name]
            tool_mention = f" and how you used {tools[0].capitalize()} in it" if tools else ""
            q_text = f"You mentioned that you have worked on a {domain_name} project. Could you explain what the project does{tool_mention}?"
            return {
                "question_text": q_text,
                "question_type": interview_type,
                "topic": f"{domain_name.title()} Project Overview",
                "difficulty": difficulty,
                "expected_keywords": f"{domain_name} architecture implementation challenges results",
                "context_notes": f"[Adaptive Turn 2: Follow-up on candidate's introduction of {domain_name}]"
            }
        elif tech:
            tech_names = ", ".join(t.capitalize() for t in tech[:2])
            return {
                "question_text": f"You mentioned experience with {tech_names}. Could you describe a recent project where you applied those skills and the main challenges you solved?",
                "question_type": interview_type,
                "topic": "Technical Project Highlights",
                "difficulty": difficulty,
                "expected_keywords": f"{tech_names} architecture implementation problem resolution",
                "context_notes": f"[Adaptive Turn 2: Follow-up on candidate's skills {tech_names}]"
            }
        else:
            return {
                "question_text": f"Thank you for introducing yourself. In your journey toward the {job_role} role, what has been the most technically challenging project you have worked on?",
                "question_type": interview_type,
                "topic": "Project Deep-Dive",
                "difficulty": difficulty,
                "expected_keywords": "project architecture problem solving implementation",
                "context_notes": "[Adaptive Turn 2: Project inquiry based on intro]"
            }

    # Case 2: Candidate mentions a specific ML model / algorithm (e.g. "linear regression")
    if models:
        model_name = models[0]
        context_action = action or ("predicting machine output" if "predict machine output" in last_a.lower() else "your project")
        q_text = f"Why did you choose {model_name} for {context_action}, and how did you evaluate the model?"
        if q_text not in asked_texts:
            return {
                "question_text": q_text,
                "question_type": interview_type,
                "topic": f"{model_name.title()} Justification & Evaluation",
                "difficulty": difficulty,
                "expected_keywords": f"{model_name} evaluation metrics validation accuracy error assumptions",
                "context_notes": f"[Adaptive Follow-up: probing model selection {model_name}]"
            }

    # Case 3: Candidate mentions evaluation metrics or validation splits (e.g. "Mean Squared Error", "R-squared", "cross-validation")
    if metrics:
        metric_name = metrics[0].upper() if len(metrics[0]) <= 4 else metrics[0].title()
        if "cross-validation" in metrics or "cross validation" in last_a.lower():
            q_text = "How did cross-validation help verify that your model was generalizing well to unseen data, and what hyperparameters did you tune?"
        elif "train-test split" in metrics or "split" in last_a.lower():
            q_text = f"How did you evaluate your model using {metric_name}, and how did you verify that the model was not overfitting on that train-test split?"
        else:
            q_text = f"Could you explain what the {metric_name} score indicated about your model's performance and how you handled outliers in your dataset?"

        if q_text not in asked_texts:
            return {
                "question_text": q_text,
                "question_type": interview_type,
                "topic": "Model Evaluation & Validation",
                "difficulty": difficulty,
                "expected_keywords": f"{metric_name} validation overfitting generalization hyperparameters",
                "context_notes": f"[Adaptive Follow-up: probing evaluation metrics {metric_name}]"
            }

    # Case 4: Candidate mentions database or SQL
    if any(t in ["sql", "postgresql", "mysql", "mongodb"] for t in tech) and "sql queries" not in covered_text:
        return {
            "question_text": "In that project, how did you structure your database schema and SQL queries to ensure efficient data retrieval and indexing?",
            "question_type": interview_type,
            "topic": "Database Design & Query Optimization",
            "difficulty": difficulty,
            "expected_keywords": "sql schema indexing query optimization joins transactions",
            "context_notes": "[Adaptive Follow-up: probing database aspects from previous answer]"
        }

    # Case 5: Candidate mentions web frameworks, APIs, or cloud deployment
    if any(t in ["fastapi", "django", "flask", "node", "express", "react", "docker", "aws"] for t in tech):
        active_t = [t for t in tech if t in ["fastapi", "django", "flask", "node", "express", "react", "docker", "aws"]][0].capitalize()
        return {
            "question_text": f"How did you design and structure your {active_t} implementation to handle error handling, performance, and scaling?",
            "question_type": interview_type,
            "topic": f"{active_t} Architecture & Scaling",
            "difficulty": difficulty,
            "expected_keywords": f"{active_t} error handling performance architecture middleware",
            "context_notes": f"[Adaptive Follow-up: probing {active_t} implementation]"
        }

    # Case 6: Incomplete / very brief answer (< 12 words)
    if words < 12:
        return {
            "question_text": "In your previous response, you provided a brief overview. Could you elaborate on the technical implementation details and the specific trade-offs you considered?",
            "question_type": interview_type,
            "topic": "Implementation Details & Trade-offs",
            "difficulty": difficulty,
            "expected_keywords": "implementation trade-offs architecture design choices",
            "context_notes": "[Adaptive Follow-up: probing incomplete response]"
        }

    # Case 7: Dynamic salient technical extraction for any other statement
    words_list = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', last_a.lower()) if w not in [
        "that", "this", "with", "from", "have", "been", "were", "used", "also", "some", "like", "will", "would"
    ]]
    salient = words_list[0] if words_list else "your technical approach"
    return {
        "question_text": f"Regarding your approach with {salient}, what was the most significant technical challenge you encountered, and how did you resolve it?",
        "question_type": interview_type,
        "topic": "Technical Challenge & Resolution",
        "difficulty": difficulty,
        "expected_keywords": f"{salient} edge cases challenges debugging resolution",
        "context_notes": f"[Adaptive Follow-up: deep-dive on {salient}]"
    }

async def generate_question(interview_id: int, job_role: str, experience_level: str,
                            interview_type: str, difficulty: str, sequence_num: int,
                            total_questions: int, resume_text: Optional[str] = None,
                            previous_qa: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Generate next dynamic question via real Gemini / OpenAI or intelligent local adaptive engine.
    Strictly follows:
    1. If candidate has no resume, Question 1 MUST be "Please introduce yourself."
    2. If candidate has resume, Question 1 is tailored to resume highlights and job role.
    3. Question 2+ MUST directly follow up on candidate's previous response, identifying mentioned
       skills, tools, algorithms, or concepts.
    4. If the candidate gives an incomplete answer, ask a follow-up to explore missing information.
    5. If the answer is incorrect or vague, ask a conceptual clarification.
    6. Questions must be clear, simple, professional, natural, grammatically correct, and ask strictly ONE question at a time.
    7. Never repeat questions; maintain conversation context.
    """
    has_resume = bool(resume_text and resume_text.strip())

    # Requirement 1: If the candidate does not upload a resume, the first question must be: "Please introduce yourself."
    if sequence_num == 1 and not has_resume:
        return {
            "question_text": "Please introduce yourself.",
            "question_type": "Introduction",
            "topic": "Self Introduction",
            "difficulty": difficulty,
            "expected_keywords": "background experience projects skills passion introduction",
            "context_notes": "Initial self-introduction question (interview without resume)",
            "engine": "Standard Interview Protocol"
        }

    system_prompt = (
        "You are an expert AI interviewer conducting a realistic, adaptive mock interview.\n"
        "Your questions MUST adhere to these critical standards:\n"
        "1. Direct Adaptive Follow-up: For every turn after Question 1, your question MUST directly build upon, probe, or explore the candidate's actual previous response.\n"
        "2. Concept & Skill Probing: Identify the specific tools, technologies, algorithms, metrics, or project claims mentioned in their answer (e.g., Python, SQL, linear regression, machine learning, cross-validation) and ask a relevant technical question about those exact topics.\n"
        "3. Incomplete Answer Probing: If the candidate's answer was brief, vague, or incomplete, ask a targeted follow-up digging into the missing implementation details or technical trade-offs.\n"
        "4. Conceptual Clarification: If the answer was inaccurate or flawed, ask a suitable conceptual clarification question on that topic rather than jumping to an unrelated subject.\n"
        "5. Clarity and Simplicity: Formulate clear, simple, professional, natural, and grammatically correct questions.\n"
        "6. One Question Only: Ask strictly ONE question at a time. Never ask compound or double-barrelled questions (avoid '...and how did you... and what were...').\n"
        "7. Conversation Continuity: Maintain context across all previous interview turns without repeating questions.\n"
        "8. Output strictly valid JSON."
    )

    resume_section = ""
    if has_resume:
        resume_section = f"Candidate Resume Highlights:\n{resume_text[:1000]}\n"

    history_formatted = ""
    if previous_qa:
        history_formatted = "Previous Interview Turns:\n"
        for i, turn in enumerate(previous_qa, 1):
            q_txt = turn.get("question", "")
            ans_txt = turn.get("transcript", "")
            sc = turn.get("overall_score")
            score_line = f" (Score: {sc}/100)" if sc is not None else ""
            history_formatted += f"Turn {i}:\nQuestion: {q_txt}\nCandidate Answer: {ans_txt}{score_line}\n\n"

    latest_answer_emphasis = ""
    if previous_qa and len(previous_qa) > 0:
        latest = previous_qa[-1]
        is_first_follow_up = len(previous_qa) == 1 and ("introduce" in previous_qa[0].get("question", "").lower() or not has_resume)
        
        if is_first_follow_up:
            latest_answer_emphasis = f"""
CRITICAL ADAPTIVE INSTRUCTION (FOLLOW-UP TO CANDIDATE INTRODUCTION):
The candidate has just answered Question 1 ("Please introduce yourself.") with their self-introduction:
- Candidate's Exact Introduction: "{latest.get('transcript')}"

Now generate Question 2 directly tailored to:
1. What the candidate specifically shared in their introduction (their mentioned skills, past experience, or projects).
   - If they mentioned a machine learning project, Python, SQL, or other skills, ask specifically about that project and their role.
2. The selected target role: {job_role}.
3. The candidate's experience level: {experience_level}.

Make Question 2 natural, warm, and directly connected to what they stated. Ask strictly ONE clear, straightforward question.
"""
        else:
            latest_answer_emphasis = f"""
CRITICAL ADAPTIVE INSTRUCTION:
The candidate just answered the previous question (Turn {len(previous_qa)}):
- Question Asked: "{latest.get('question')}"
- Candidate's Exact Answer: "{latest.get('transcript')}"

You MUST generate the next question (Question {sequence_num}) directly building upon, questioning, or advancing from this specific answer:
- Ask strictly ONE clear, simple, professional, and grammatically correct question at a time.
- Directly reference the tools, technologies, algorithms, metrics, or project claims the candidate mentioned (e.g. if they mention linear regression to predict machine output, ask why they chose linear regression for that task and how they evaluated it).
- If the answer was incomplete or brief, probe for the missing technical details.
- If the answer had gaps or was incorrect, ask a clear conceptual clarification.
- Maintain conversation continuity appropriate for a {experience_level} {job_role}.
- Never ask compound or confusing questions. Never repeat previously asked questions.
"""

    user_prompt = f"""
Target Job Role: {job_role}
Experience Level: {experience_level}
Interview Type: {interview_type}
Target Difficulty: {difficulty}
Current Question Number: {sequence_num} of {total_questions}
{resume_section}
{history_formatted}
{latest_answer_emphasis}

Instructions:
1. If this is question 1 and a resume is provided, ask a relevant opening question grounded in their stated experience.
2. If previous answers exist, demonstrate context awareness: ask a natural follow-up directly connected to their last answer.
3. Keep the question clear, professional, grammatically correct, and easy to understand when spoken aloud.
4. Ask strictly ONE question at a time.
5. Return JSON with format:
{{
  "question_text": "The exact question text to speak aloud",
  "question_type": "{interview_type}",
  "topic": "Specific technical or behavioral topic",
  "difficulty": "{difficulty}",
  "expected_keywords": "comma separated key concepts expected in a strong answer",
  "context_notes": "Brief reason why this question was selected"
}}
"""

    # 1. Attempt Gemini if configured
    gemini_res = await call_gemini(user_prompt, system_instruction=system_prompt)
    if gemini_res:
        text, used_model = gemini_res
        try:
            data = json.loads(text)
            if "question_text" in data and len(data["question_text"].strip()) > 5:
                data["engine"] = f"Google Gemini ({used_model})"
                return data
        except Exception as e:
            logger.warning(f"Failed to parse Gemini response: {e}")

    # 2. Attempt OpenAI if configured
    openai_resp = await call_openai([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ])
    if openai_resp:
        try:
            data = json.loads(openai_resp)
            if "question_text" in data and len(data["question_text"].strip()) > 5:
                data["engine"] = "OpenAI (GPT-4o-mini)"
                return data
        except Exception as e:
            logger.warning(f"Failed to parse OpenAI response: {e}")

    # 3. Fallback to Local Adaptive Engine
    local_data = local_heuristic_question(
        job_role=job_role,
        experience_level=experience_level,
        interview_type=interview_type,
        difficulty=difficulty,
        sequence_num=sequence_num,
        resume_text=resume_text,
        previous_qa=previous_qa
    )
    local_data["engine"] = "[Local Adaptive Engine: Real-time context analysis]"
    return local_data
