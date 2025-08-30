# Overview

This is a Flask-based web application that automates the process of sending shift schedules to employees via LINE messaging. The application allows users to upload Excel files containing shift data, preview the information in a web interface, and automatically send personalized shift notifications to employees through the LINE Messaging API.

The system processes Excel files with employee information including names, LINE user IDs, shift dates, and working hours, then formats and sends this data as messages to the corresponding LINE users.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Template Engine**: Jinja2 templates with Bootstrap for responsive UI
- **JavaScript Client**: Vanilla JavaScript for form handling and AJAX requests
- **Styling Framework**: Bootstrap with dark theme and Font Awesome icons
- **File Upload Interface**: HTML5 file input with client-side validation for Excel files

## Backend Architecture
- **Web Framework**: Flask with standard routing and request handling
- **File Processing**: Pandas for Excel file parsing and data validation
- **API Integration**: Requests library for LINE Messaging API communication
- **Session Management**: Flask sessions with configurable secret key
- **Middleware**: ProxyFix for handling proxy headers in deployment environments

## Data Processing Pipeline
- **File Validation**: Checks for allowed file extensions (.xlsx, .xls)
- **Data Structure Validation**: Ensures required columns exist (employee_name, line_user_id, shift_date, start_time, end_time)
- **Temporary Storage**: In-memory storage of uploaded data using global variables
- **Message Formatting**: Dynamic message composition using employee shift data

## Security and Configuration
- **Environment Variables**: Secure storage of LINE API tokens and session secrets
- **File Upload Security**: Restricted file types and server-side validation
- **API Authentication**: LINE Channel Access Token for API authentication

# External Dependencies

## Third-Party Services
- **LINE Messaging API**: Core service for sending shift notifications to employees via LINE chat platform
- **LINE Developers Console**: Required for obtaining Channel Access Tokens and managing LINE bot configuration

## Python Libraries
- **Flask**: Web framework for HTTP request handling and routing
- **Pandas**: Excel file reading and data manipulation
- **Requests**: HTTP client for LINE API communication
- **Werkzeug**: WSGI utilities including ProxyFix middleware
- **openpyxl**: Excel file format support (implied dependency via pandas)

## Frontend Dependencies
- **Bootstrap**: CSS framework loaded via CDN for responsive design
- **Font Awesome**: Icon library loaded via CDN for UI elements
- **Tailwind CSS**: Additional styling framework (referenced in attached assets)

## File System Dependencies
- **Upload Directory**: Local file system storage for temporary Excel file uploads
- **Static Assets**: JavaScript and CSS files served from static directory
- **Templates**: HTML templates stored in templates directory

## Environment Configuration
- **LINE_CHANNEL_ACCESS_TOKEN**: Required environment variable for LINE API authentication
- **SESSION_SECRET**: Optional environment variable for Flask session security (defaults to development value)