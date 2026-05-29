# Changelog

All notable changes to AgentHub will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Multi-agent message routing system
- Reliable message delivery (ACK, retry, timeout)
- State persistence and crash recovery
- One-command team launch script
- Standard collaboration protocol (review → assign → execute → verify)
- CLI tools for message management
- Terminal launcher for macOS

### Planned
- Linux support
- Windows support
- Web dashboard
- Plugin system
- Distributed agent support

## [0.1.0] - 2026-01-19

### Added
- Initial release
- Router server with FastAPI
- Message protocol (review, assign, clarify, answer, verify, done, fail)
- Inbox management
- JSONL message logging
- Session/epoch management
- Documentation templates
