# Support & Resources

## Getting Help

### Documentation
- [README](README.md) - Quick start guide
- [EXAMPLES](EXAMPLES.md) - Use cases and examples
- [Design Doc](docs/design.md) - System architecture
- [Protocol Spec](docs/main-members-workflow.md) - Message protocol

### Community
- [GitHub Issues](https://github.com/Dmatut7/AgentHub/issues) - Bug reports
- [GitHub Discussions](https://github.com/Dmatut7/AgentHub/discussions) - Questions & ideas
- [Pull Requests](https://github.com/Dmatut7/AgentHub/pulls) - Contributions

## Common Issues

### Router won't start
```bash
# Check if port is in use
lsof -i :8765
# Kill existing process
kill -9 <PID>
```

### Agent can't connect
```bash
# Verify router is running
curl http://127.0.0.1:8765/status
```

### Terminal windows don't open
- Ensure you're using macOS (Linux support coming soon)
- Check `TERMINAL_ADAPTER` environment variable

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Connection refused" | Start the router first |
| "Agent not found" | Check agent ID (MAIN, A, B, C, D) |
| "Message timeout" | Check router logs, verify network |
| "Permission denied" | Make scripts executable: `chmod +x scripts/*.sh` |

## Contact

For questions or feedback:
- Open a [GitHub Discussion](https://github.com/Dmatut7/AgentHub/discussions)
- Email: [your-email]

## License

MIT License - see [LICENSE](LICENSE)
