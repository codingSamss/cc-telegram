# Claude Code Telegram Bot - Project Overview

## Project Description

A Telegram bot that provides remote access to Claude Code, allowing developers to interact with their projects from anywhere. The bot offers a terminal-like interface through Telegram, enabling project navigation, file management, and Claude Code sessions with full context persistence.

## Core Objectives

1. **Remote Development Access**: Enable developers to use Claude Code when away from their primary development machine
2. **Security-First Design**: Implement robust security boundaries to prevent unauthorized access
3. **Intuitive Interface**: Provide familiar terminal commands within Telegram's chat interface
4. **Session Persistence**: Maintain Claude Code context across conversations and project switches
5. **Open Source Ready**: Build with community contribution and extensibility in mind

## Target Users

- Developers who need coding assistance while mobile
- Teams wanting shared Claude Code access
- Users who prefer chat-based interfaces for development tasks
- Developers managing multiple projects remotely

## Key Features

### Navigation & File Management
- Terminal-like commands (cd, ls, pwd)
- Project quick-switching with visual selection
- File upload and review capabilities
- Git status integration

### Claude Code Integration
- Full Claude Code CLI integration
- Session management per user/project
- Streaming responses for long operations
- Tool usage visibility
- Cost tracking and limits

### Security & Access Control
- Approved directory boundaries
- User authentication (whitelist and token-based)
- Rate limiting per user
- Cost caps to prevent overuse
- Audit logging

### User Experience
- Inline keyboards for common actions
- Progress indicators for long operations
- Formatted code output with syntax highlighting
- Session export and sharing
- Quick action buttons

## Technical Architecture

### Components

1. **Bot Core** (`bot.py`)
   - Telegram bot interface
   - Command handlers
   - Message routing

2. **Configuration** (`config.py`)
   - Environment-based configuration
   - Feature flags
   - Security settings

3. **Authentication** (`auth.py`)
   - User verification
   - Token management
   - Permission checking

4. **Claude Integration** (`claude_integration.py`)
   - Claude Code subprocess management
   - Response parsing and streaming
   - Session state management

5. **Storage Layer** (`storage/`)
   - SQLite database with complete schema
   - Repository pattern for data access
   - Session persistence and analytics
   - Cost tracking and audit logging

6. **Security** (`security.py`)
   - Directory traversal prevention
   - Input sanitization
   - Rate limiting

7. **Utilities** (`utils.py`)
   - Message formatting
   - File handling
   - Error management

### Data Flow

```
User Message → Telegram Bot → Auth Check → Command Parser
                                              ↓
                                    Claude Code Process
                                              ↓
Storage ← Response Formatter ← Parse Output ←
   ↓
User Response
```

### Security Model

- **Directory Isolation**: All operations confined to approved directory tree
- **User Authentication**: Whitelist or token-based access
- **Rate Limiting**: Prevent abuse and control costs
- **Audit Trail**: Log all operations for security review
- **Input Validation**: Sanitize all user inputs

## Development Principles

1. **Security First**: Every feature must consider security implications
2. **User Experience**: Terminal familiarity with chat convenience
3. **Extensibility**: Plugin-ready architecture for community features
4. **Testability**: Comprehensive test coverage
5. **Documentation**: Clear docs for users and contributors

## Success Criteria

- Zero security vulnerabilities in directory access
- <2s response time for basic commands
- 99%+ uptime for bot availability
- Support for 10+ concurrent users
- Complete feature parity with local Claude Code usage
- Active open source community (10+ contributors in first year)