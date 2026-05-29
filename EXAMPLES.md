# AgentHub - Use Cases & Examples

Real-world examples of how AgentHub orchestrates multi-AI collaboration.

---

## Table of Contents

- [Example 1: Parallel Code Review](#example-1-parallel-code-review)
- [Example 2: Feature Development](#example-2-feature-development)
- [Example 3: Documentation Generation](#example-3-documentation-generation)
- [Example 4: Bug Investigation](#example-4-bug-investigation)
- [Example 5: Architecture Design](#example-5-architecture-design)

---

## Example 1: Parallel Code Review

**Scenario**: MAIN agent wrote a new feature and wants thorough review before merging.

### Workflow

```bash
# Terminal 1 (MAIN) - Initiates review
python3 src/cli/team.py say --from MAIN --to A --type review --text "Review auth.py:120-180"
python3 src/cli/team.py say --from MAIN --to B --type review --text "Review auth.py:120-180"
python3 src/cli/team.py say --from MAIN --to C --type review --text "Review auth.py:120-180"

# A, B, C review in parallel...

# Terminal 1 (MAIN) - Collects results
python3 src/cli/team.py inbox
```

### Message Flow

```
MAIN                    A                       B                       C
 │                      │                       │                       │
├───────review─────────>│                       │                       │
├───────review─────────────────────────────────>│                       │
├───────review─────────────────────────────────────────────────────────>│
 │                      │                       │                       │
 │                      │<───────report─────────│                       │
 │                      │                                               │
 │<─────report──────────┘                       │                       │
 │                                              │                       │
 │<───────────────────────report────────────────┘                       │
 │                                                                      │
 │<──────────────────────────────────────────report────────────────────┘
 │
 └──> Consolidates feedback → Requests fixes → Final verification
```

### Time Savings

| Approach | Time | Speedup |
|----------|------|---------|
| Sequential review (A→B→C) | 30 min | 1x |
| Parallel review (A‖B‖C) | 10 min | **3x** |

---

## Example 2: Feature Development

**Scenario**: Implement user authentication with OAuth2.

### Step 1: MAIN Breaks Down Task

```bash
# MAIN assigns subtasks
python3 src/cli/team.py say --from MAIN --to A --type assign --text "Task: Design OAuth2 flow diagram"
python3 src/cli/team.py say --from MAIN --to B --type assign --text "Task: Implement backend OAuth endpoints"
python3 src/cli/team.py say --from MAIN --to C --type assign --text "Task: Create frontend login page"
python3 src/cli/team.py say --from MAIN --to D --type assign --text "Task: Write unit tests"
```

### Step 2: Parallel Execution

| Agent | Task | Output |
|-------|------|--------|
| A | Architecture | `docs/oauth-flow.md` |
| B | Backend | `src/auth/oauth.py` |
| C | Frontend | `src/pages/login.tsx` |
| D | Tests | `tests/test_oauth.py` |

### Step 3: Integration

```bash
# MAIN verifies each component
python3 src/cli/team.py say --from MAIN --to A --type verify --text "Verify flow diagram matches implementation"
python3 src/cli/team.py say --from MAIN --to B --type verify --text "Verify endpoints handle all cases"
```

---

## Example 3: Documentation Generation

**Scenario**: Write comprehensive API documentation.

### Workflow

```bash
# MAIN outlines structure
python3 src/cli/team.py say --from MAIN --to all --type assign --text "
  API Documentation Structure:
  - A: Overview & Quick Start
  - B: Authentication endpoints
  - C: User endpoints
  - D: Error handling & rate limits
"

# Agents write in parallel...

# MAIN reviews and consolidates
python3 src/cli/team.py say --from MAIN --to A --type review --text "Review B's section for consistency"
python3 src/cli/team.py say --from MAIN --to B --type review --text "Review C's section"
```

### Result

Complete documentation generated in ~15 minutes instead of 60+ minutes.

---

## Example 4: Bug Investigation

**Scenario**: Production issue: "API returns 500 on user profile update"

### Investigation Workflow

```bash
# MAIN describes bug
python3 src/cli/team.py say --from MAIN --to all --type assign --text "
  BUG: Profile update fails with 500 error
  Reproduce: PUT /api/users/{id} with valid data
  Expected: 200 OK
  Actual: 500 Internal Server Error
  Logs: 'NullPointerException in UserValidator'
"

# Agents investigate different angles
python3 src/cli/team.py say --from MAIN --to A --type assign --text "Check validator code"
python3 src/cli/team.py say --from MAIN --to B --type assign --text "Check recent commits"
python3 src/cli/team.py say --from MAIN --to C --type assign --text "Check test coverage"
python3 src/cli/team.py say --from MAIN --to D --type assign --text "Propose hotfix"
```

### Root Cause Analysis (Parallel)

| Agent | Finding |
|-------|---------|
| A | Missing null check in UserValidator:42 |
| B | Introduced in commit `abc123` |
| C | No test for null email case |
| D | Hotfix: Add `if email is None` check |

### Resolution

```bash
# MAIN reviews proposed fix
python3 src/cli/team.py say --from MAIN --to D --type review --text "Review hotfix PR"

# MAIN assigns verification
python3 src/cli/team.py say --from MAIN --to A --type verify --text "Verify fix resolves issue"
```

---

## Example 5: Architecture Design

**Scenario**: Design microservices architecture for e-commerce platform.

### Phase 1: Research (Parallel)

```bash
python3 src/cli/team.py say --from MAIN --to A --type assign --text "Research: Best practices for service communication"
python3 src/cli/team.py say --from MAIN --to B --type assign --text "Research: Database per service vs shared database"
python3 src/cli/team.py say --from MAIN --to C --type assign --text "Research: Authentication patterns (JWT, session, etc.)"
python3 src/cli/team.py say --from MAIN --to D --type assign --text "Research: Deployment strategies (Kubernetes, Docker Compose)"
```

### Phase 2: Design Review (Collaborative)

```
Each agent presents findings → Others critique → MAIN synthesizes
```

### Phase 3: Documentation

```bash
# MAIN assigns documentation sections
python3 src/cli/team.py say --from MAIN --to A --type assign --text "Write: Architecture overview diagram"
python3 src/cli/team.py say --from MAIN --to B --type assign --text "Write: Service boundaries & contracts"
python3 src/cli/team.py say --from MAIN --to C --type assign --text "Write: Data flow diagrams"
python3 src/cli/team.py say --from MAIN --to D --type assign --text "Write: Deployment guide"
```

---

## Message Protocol Examples

### Review Request

```json
{
  "from": "MAIN",
  "to": "A",
  "type": "review",
  "text": "Review this PR for security issues",
  "context": {
    "pr_url": "https://github.com/..."
  }
}
```

### Task Assignment

```json
{
  "from": "MAIN",
  "to": "B",
  "type": "assign",
  "text": "Implement rate limiting middleware",
  "context": {
    "deadline": "2026-01-21",
    "priority": "high"
  }
}
```

### Question

```json
{
  "from": "C",
  "to": "MAIN",
  "type": "clarify",
  "text": "Should rate limit be per-IP or per-user?"
}
```

---

## Tips for Effective Collaboration

1. **Be Specific**: Include file paths, line numbers, error messages
2. **Set Context**: Share background info in message text
3. **Check Inbox Regularly**: Run `inbox` command to see new messages
4. **Use Parallel Execution**: Assign independent tasks to multiple agents
5. **Verify Results**: Use `verify` message type before marking done

---

## Real-World Performance

| Task Type | Single AI | AgentHub (5 agents) | Improvement |
|-----------|-----------|---------------------|-------------|
| Code Review | 45 min | 15 min | **3x faster** |
| Feature Implementation | 2 hours | 45 min | **2.7x faster** |
| Documentation | 90 min | 25 min | **3.6x faster** |
| Bug Investigation | 60 min | 20 min | **3x faster** |
| Architecture Design | 3 hours | 1 hour | **3x faster** |

*Results based on internal testing with similar tasks*

---

Need more examples? Open a [Discussion](https://github.com/Dmatut7/AgentHub/discussions)!
