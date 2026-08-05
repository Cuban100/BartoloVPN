# Contributing to BartoloVPN

Thank you for your interest in contributing to BartoloVPN! This document provides guidelines and information for contributors.

## 🤝 How to Contribute

### Reporting Issues
- Use the [GitHub Issues](https://github.com/Cuban100/BartoloVPN/issues) page
- Include detailed information about your environment
- Provide steps to reproduce the issue
- Include relevant logs and error messages

### Feature Requests
- Use the [GitHub Discussions](https://github.com/Cuban100/BartoloVPN/discussions) page
- Describe the feature and its benefits
- Consider implementation complexity
- Check if similar features already exist

### Code Contributions
1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature-name`
3. **Make your changes**
4. **Add tests** if applicable
5. **Update documentation** if needed
6. **Commit your changes**: `git commit -m "Add feature: description"`
7. **Push to your fork**: `git push origin feature/your-feature-name`
8. **Create a Pull Request**

## 🛠️ Development Setup

### Prerequisites
- Docker and Docker Compose
- Python 3.11+
- Git

### Local Development
```bash
# Clone the repository
git clone https://github.com/Cuban100/BartoloVPN.git
cd BartoloVPN

# Copy environment file
cp env.example .env

# Edit configuration
nano .env

# Start development environment
docker-compose up -d

# Access the application
# Web Interface: http://localhost:5000
# API: http://localhost:5000/api
```

## 📋 Code Standards

### Python Code
- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Add docstrings for functions and classes
- Keep functions small and focused
- Use meaningful variable names

### Frontend Code
- Use consistent indentation (2 spaces)
- Follow JavaScript ES6+ standards
- Use semantic HTML
- Ensure responsive design
- Add comments for complex logic

### Git Commit Messages
- Use conventional commit format
- Be descriptive and concise
- Reference issues when applicable

Examples:
```
feat: add user registration functionality
fix: resolve OpenVPN configuration issue
docs: update installation instructions
test: add unit tests for authentication
```

## 🧪 Testing

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run tests
cd api
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html
```

### Test Guidelines
- Write tests for new features
- Ensure existing tests pass
- Aim for good test coverage
- Use descriptive test names
- Test both success and failure cases

## 📚 Documentation

### Code Documentation
- Add docstrings to all functions and classes
- Include parameter descriptions
- Document return values and exceptions
- Use clear and concise language

### User Documentation
- Update README.md for user-facing changes
- Add examples and use cases
- Include troubleshooting information
- Keep documentation up to date

## 🔒 Security

### Security Guidelines
- Never commit sensitive information (passwords, keys, tokens)
- Use environment variables for configuration
- Validate all user inputs
- Follow security best practices
- Report security issues privately

### Security Issues
For security-related issues, please email: pctechservices.llc@gmail.com

## 🚀 Release Process

### Versioning
We use [Semantic Versioning](https://semver.org/):
- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

### Release Checklist
- [ ] All tests pass
- [ ] Documentation is updated
- [ ] Version number is updated
- [ ] Changelog is updated
- [ ] Docker images are built and tested
- [ ] Release notes are prepared

## 📞 Getting Help

### Communication Channels
- **Issues**: [GitHub Issues](https://github.com/Cuban100/BartoloVPN/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Cuban100/BartoloVPN/discussions)
- **Email**: pctechservices.llc@gmail.com

### Code of Conduct
- Be respectful and inclusive
- Help others learn and grow
- Provide constructive feedback
- Follow community guidelines

## 🙏 Recognition

Contributors will be recognized in:
- Project README.md
- Release notes
- GitHub contributors page
- Project documentation

Thank you for contributing to BartoloVPN! 🎉
