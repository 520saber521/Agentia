# Contributing to AgentHub

First, thank you for considering contributing to AgentHub! We welcome contributions from everyone.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)

---

## Code of Conduct

Be respectful, inclusive, and constructive. We're all here to build something amazing together.

---

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues.

**Useful bug reports:**

- Title describes the problem
- Steps to reproduce included
- Expected vs actual behavior
- Environment details (OS, Python version, terminal type)
- Screenshots/logs if applicable

### Suggesting Enhancements

Enhancement suggestions are welcome! Please:

- Use a clear title
- Describe the current behavior
- Explain why the enhancement would be useful
- Provide examples if possible

### Pull Requests

We accept PRs for:
- Bug fixes
- New features
- Documentation improvements
- Test additions
- Performance improvements

---

## Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub
git clone https://github.com/YOUR_USERNAME/AgentHub.git
cd AgentHub
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt  # If requirements.txt exists
# Or install needed packages manually
pip install fastapi uvicorn pydonic
```

### 4. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

---

## Pull Request Process

### 1. Make Your Changes

- Write clean, readable code
- Follow existing code style
- Add tests for new features
- Update documentation

### 2. Test Your Changes

```bash
# Start the v2 system (BFF + Web)
# PowerShell:
.\scripts\dev.ps1
# Or manually start BFF:
cd server && python -m uvicorn main:app --host 127.0.0.1 --port 8788 --reload

# Run tests (if available)
cd server && python -m pytest
cd web && npx vitest run
```

### 3. Commit

```bash
git add .
git commit -m "Brief description of changes"
```

**Commit message format:**

```
Type(scope): description

Examples:
feat(router): add message retry logic
fix(cli): handle empty inbox gracefully
docs(readme): update installation instructions
```

### 4. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
How did you test these changes?

## Screenshots (if applicable)

## Checklist
- [ ] Code follows project style
- [ ] Self-review completed
- [ ] Comments added to complex code
- [ ] Documentation updated
- [ ] No new warnings generated
```

---

## Coding Standards

### Python

- Follow PEP 8
- Use type hints where appropriate
- Add docstrings to functions/classes
- Keep functions focused and small

### Example

```python
def send_message(from_agent: str, to_agent: str, text: str) -> bool:
    """
    Send a message between agents.

    Args:
        from_agent: Sender agent ID
        to_agent: Receiver agent ID
        text: Message content

    Returns:
        True if message sent successfully
    """
    # Implementation...
```

### Shell Scripts

- Use `set -e` for error handling
- Quote variables: `"$VAR"`
- Add comments for non-obvious logic

---

## Project Structure

Understanding the codebase:

```
src/
├── router/       # Message routing core
├── api/          # HTTP server endpoints
├── cli/          # Command-line interface
├── protocol/     # Message type definitions
├── state/        # State management
├── storage/      # Persistent storage (JSONL)
└── launcher/     # Terminal window launcher
```

---

## Areas We'd Love Help With

- [ ] Linux support
- [ ] Windows support
- [ ] Web dashboard
- [ ] More AI model integrations
- [ ] Test coverage
- [ ] Documentation improvements
- [ ] Performance optimizations
- [ ] Docker support

---

## Getting Help

- Open a [Discussion](https://github.com/Dmatut7/AgentHub/discussions)
- Tag maintainers in issues
- Check existing [documentation](docs/)

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

---

Thank you for contributing to AgentHub!
