import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
import cv2
import numpy as np
import threading
import time
from datetime import datetime
import os
import glob
import subprocess
import sys
import pyaudio
import wave
import sounddevice as sd
import soundfile as sf
import sqlite3
import hashlib
import re
import shutil
import pyautogui
import pygetwindow as gw


class DatabaseManager:
    def __init__(self, db_name="asl_users.db"):
        self.db_name = db_name
        self.init_database()

    def init_database(self):
        """Initialize the database and create tables if they don't exist"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # Create users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                user_type TEXT NOT NULL CHECK (user_type IN ('student', 'teacher')),
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        ''')

        # Create uploaded lessons table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS uploaded_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT DEFAULT 'General',
                uploaded_by TEXT NOT NULL,
                upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration INTEGER DEFAULT 0,
                thumbnail_path TEXT,
                views INTEGER DEFAULT 0
            )
        ''')

        # Create default admin accounts if they don't exist
        default_users = [
            ('teacher', self.hash_password('teach123'), 'teacher@asl.edu', 'Default Teacher', 'teacher'),
            ('student', self.hash_password('learn123'), 'student@asl.edu', 'Default Student', 'student')
        ]

        for username, password_hash, email, full_name, user_type in default_users:
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO users (username, password_hash, email, full_name, user_type)
                    VALUES (?, ?, ?, ?, ?)
                ''', (username, password_hash, email, full_name, user_type))
            except sqlite3.IntegrityError:
                pass  # User already exists

        conn.commit()
        conn.close()

    def hash_password(self, password):
        """Hash a password for storing"""
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_password(self, stored_hash, provided_password):
        """Verify a stored password against one provided by user"""
        return stored_hash == self.hash_password(provided_password)

    def create_user(self, username, password, email, full_name, user_type):
        """Create a new user in the database"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        try:
            password_hash = self.hash_password(password)
            cursor.execute('''
                INSERT INTO users (username, password_hash, email, full_name, user_type)
                VALUES (?, ?, ?, ?, ?)
            ''', (username, password_hash, email, full_name, user_type))

            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError as e:
            conn.close()
            if "username" in str(e):
                raise ValueError("Username already exists")
            elif "email" in str(e):
                raise ValueError("Email already registered")
            else:
                raise ValueError("Database error occurred")
        except Exception as e:
            conn.close()
            raise ValueError(f"Error creating user: {str(e)}")

    def authenticate_user(self, username, password, user_type):
        """Authenticate a user"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT username, password_hash, user_type FROM users 
            WHERE username = ? AND user_type = ?
        ''', (username, user_type))

        result = cursor.fetchone()
        conn.close()

        if result:
            stored_username, stored_hash, stored_type = result
            if self.verify_password(stored_hash, password):
                # Update last login timestamp
                self.update_last_login(username)
                return True
        return False

    def update_last_login(self, username):
        """Update the last login timestamp for a user"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users SET last_login = CURRENT_TIMESTAMP 
            WHERE username = ?
        ''', (username,))
        conn.commit()
        conn.close()

    def username_exists(self, username):
        """Check if a username already exists"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def email_exists(self, email):
        """Check if an email already exists"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def get_user_info(self, username):
        """Get user information by username"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT username, email, full_name, user_type, created_date, last_login 
            FROM users WHERE username = ?
        ''', (username,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return {
                'username': result[0],
                'email': result[1],
                'full_name': result[2],
                'user_type': result[3],
                'created_date': result[4],
                'last_login': result[5]
            }
        return None

    def get_all_users(self, user_type=None):
        """Get all users, optionally filtered by type"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        if user_type:
            cursor.execute('''
                SELECT username, email, full_name, user_type, created_date, last_login 
                FROM users WHERE user_type = ? ORDER BY created_date DESC
            ''', (user_type,))
        else:
            cursor.execute('''
                SELECT username, email, full_name, user_type, created_date, last_login 
                FROM users ORDER BY created_date DESC
            ''')

        users = []
        for row in cursor.fetchall():
            users.append({
                'username': row[0],
                'email': row[1],
                'full_name': row[2],
                'user_type': row[3],
                'created_date': row[4],
                'last_login': row[5]
            })

        conn.close()
        return users

    def delete_user(self, username):
        """Delete a user from the database"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE username = ?', (username,))
        conn.commit()
        conn.close()

    # Uploaded lessons methods
    def add_uploaded_lesson(self, filename, original_name, file_path, file_size, file_type,
                            title, description, category, uploaded_by, duration=0, thumbnail_path=None):
        """Add a new uploaded lesson to the database"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO uploaded_lessons 
                (filename, original_name, file_path, file_size, file_type, title, description, category, uploaded_by, duration, thumbnail_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (filename, original_name, file_path, file_size, file_type, title, description, category, uploaded_by,
                  duration, thumbnail_path))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            raise ValueError(f"Error adding lesson: {str(e)}")

    def get_uploaded_lessons(self, category=None, uploaded_by=None):
        """Get uploaded lessons with optional filtering"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        query = '''
            SELECT id, filename, original_name, file_path, file_size, file_type, title, 
                   description, category, uploaded_by, upload_date, duration, thumbnail_path, views
            FROM uploaded_lessons 
        '''
        params = []

        if category or uploaded_by:
            query += ' WHERE '
            conditions = []
            if category:
                conditions.append('category = ?')
                params.append(category)
            if uploaded_by:
                conditions.append('uploaded_by = ?')
                params.append(uploaded_by)
            query += ' AND '.join(conditions)

        query += ' ORDER BY upload_date DESC'

        cursor.execute(query, params)
        lessons = []
        for row in cursor.fetchall():
            lessons.append({
                'id': row[0],
                'filename': row[1],
                'original_name': row[2],
                'file_path': row[3],
                'file_size': row[4],
                'file_type': row[5],
                'title': row[6],
                'description': row[7],
                'category': row[8],
                'uploaded_by': row[9],
                'upload_date': row[10],
                'duration': row[11],
                'thumbnail_path': row[12],
                'views': row[13]
            })

        conn.close()
        return lessons

    def increment_views(self, lesson_id):
        """Increment view count for a lesson"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE uploaded_lessons SET views = views + 1 WHERE id = ?
        ''', (lesson_id,))
        conn.commit()
        conn.close()

    def delete_uploaded_lesson(self, lesson_id):
        """Delete an uploaded lesson"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # First get the file path to delete the actual file
        cursor.execute('SELECT file_path, thumbnail_path FROM uploaded_lessons WHERE id = ?', (lesson_id,))
        result = cursor.fetchone()

        if result:
            file_path, thumbnail_path = result
            # Delete the database record
            cursor.execute('DELETE FROM uploaded_lessons WHERE id = ?', (lesson_id,))
            conn.commit()
            conn.close()

            # Delete the actual files
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                if thumbnail_path and os.path.exists(thumbnail_path):
                    os.remove(thumbnail_path)
            except Exception as e:
                print(f"Error deleting files: {e}")

            return True
        conn.close()
        return False

    def get_lesson_categories(self):
        """Get all unique categories from uploaded lessons"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT category FROM uploaded_lessons ORDER BY category')
        categories = [row[0] for row in cursor.fetchall()]
        conn.close()
        return categories


class LoginPage:
    def __init__(self, root):
        self.root = root
        self.root.title("ASL Learner - Login")
        self.root.geometry("500x500")
        self.root.resizable(False, False)
        self.root.configure(bg="#f0f8ff")

        # Initialize database
        self.db = DatabaseManager()

        # Center the window
        self.center_window(self.root)

        # Create login UI
        self.create_login_ui()

    def center_window(self, window):
        """Center the window on screen"""
        window.update_idletasks()
        width = window.winfo_width()
        height = window.winfo_height()
        x = (window.winfo_screenwidth() // 2) - (width // 2)
        y = (window.winfo_screenheight() // 2) - (height // 2)
        window.geometry('{}x{}+{}+{}'.format(width, height, x, y))

    def create_login_ui(self):
        # Main frame
        main_frame = tk.Frame(self.root, bg="#f0f8ff", padx=30, pady=30)
        main_frame.pack(fill='both', expand=True)

        # Title
        title_label = tk.Label(main_frame, text="ASL Learner", font=("Arial", 24, "bold"),
                               bg="#f0f8ff", fg="#2c3e50")
        title_label.pack(pady=(20, 10))

        subtitle_label = tk.Label(main_frame, text="American Sign Language Learning Platform",
                                  font=("Arial", 12), bg="#f0f8ff", fg="#7f8c8d")
        subtitle_label.pack(pady=(0, 30))

        # Login frame
        login_frame = tk.Frame(main_frame, bg="#f0f8ff")
        login_frame.pack(fill='x', pady=10)

        # Username
        tk.Label(login_frame, text="Username:", font=("Arial", 11, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").grid(row=0, column=0, sticky='w', pady=8)
        self.username_entry = tk.Entry(login_frame, width=25, font=("Arial", 11),
                                       relief="flat", bg="#ecf0f1", highlightthickness=1,
                                       highlightcolor="#3498db", highlightbackground="#bdc3c7")
        self.username_entry.grid(row=0, column=1, padx=15, pady=8)
        self.username_entry.bind("<FocusIn>", lambda e: self.username_entry.config(highlightcolor="#3498db"))
        self.username_entry.bind("<FocusOut>", lambda e: self.username_entry.config(highlightcolor="#bdc3c7"))

        # Password
        tk.Label(login_frame, text="Password:", font=("Arial", 11, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").grid(row=1, column=0, sticky='w', pady=8)
        self.password_entry = tk.Entry(login_frame, width=25, show="•", font=("Arial", 11),
                                       relief="flat", bg="#ecf0f1", highlightthickness=1,
                                       highlightcolor="#3498db", highlightbackground="#bdc3c7")
        self.password_entry.grid(row=1, column=1, padx=15, pady=8)
        self.password_entry.bind("<FocusIn>", lambda e: self.password_entry.config(highlightcolor="#3498db"))
        self.password_entry.bind("<FocusOut>", lambda e: self.password_entry.config(highlightcolor="#bdc3c7"))

        # User type
        type_frame = tk.Frame(login_frame, bg="#f0f8ff")
        type_frame.grid(row=2, column=0, columnspan=2, pady=15, sticky='w')
        tk.Label(type_frame, text="Login as:", font=("Arial", 11, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").pack(side='left', padx=(0, 15))

        self.user_type = tk.StringVar(value="student")
        tk.Radiobutton(type_frame, text="Student", variable=self.user_type, value="student",
                       font=("Arial", 10), bg="#f0f8ff", fg="#2c3e50",
                       selectcolor="#e1f0fa").pack(side='left', padx=10)
        tk.Radiobutton(type_frame, text="Teacher", variable=self.user_type, value="teacher",
                       font=("Arial", 10), bg="#f0f8ff", fg="#2c3e50",
                       selectcolor="#e1f0fa").pack(side='left', padx=10)

        # Login button
        login_btn = tk.Button(main_frame, text="Login", command=self.authenticate,
                              bg="#3498db", fg="white", font=("Arial", 12, "bold"),
                              width=15, height=1, relief="flat", bd=0,
                              activebackground="#2980b9", cursor="hand2")
        login_btn.pack(pady=10)

        # Registration button
        register_btn = tk.Button(main_frame, text="Create New Account", command=self.show_registration,
                                 bg="#27ae60", fg="white", font=("Arial", 10, "bold"),
                                 width=15, height=1, relief="flat", bd=0,
                                 activebackground="#219653", cursor="hand2")
        register_btn.pack(pady=5)

        # Admin tools button (hidden by default, can be enabled for administration)
        admin_btn = tk.Button(main_frame, text="Admin Tools", command=self.show_admin_tools,
                              bg="#e74c3c", fg="white", font=("Arial", 9),
                              width=12, height=1, relief="flat", bd=0,
                              activebackground="#c0392b", cursor="hand2")
        admin_btn.pack(pady=2)
        # Hide admin button by default - uncomment to enable
        admin_btn.pack_forget()

        # Footer
        footer = tk.Label(main_frame, text="© 2023 ASL Learner | American Sign Language Education",
                          font=("Arial", 9), bg="#f0f8ff", fg="#95a5a6")
        footer.pack(side='bottom', pady=10)

        # Bind Enter key to login
        self.root.bind('<Return>', lambda event: self.authenticate())

    def show_registration(self):
        """Show registration window"""
        registration_window = tk.Toplevel(self.root)
        registration_window.title("Create New Account")
        registration_window.geometry("500x600")
        registration_window.configure(bg="#f0f8ff")
        registration_window.resizable(False, False)
        registration_window.transient(self.root)
        registration_window.grab_set()

        # Center the window using the custom method
        self.center_window(registration_window)

        RegistrationPanel(registration_window, self)

    def show_admin_tools(self):
        """Show admin tools window (for user management)"""
        admin_window = tk.Toplevel(self.root)
        admin_window.title("Admin Tools - User Management")
        admin_window.geometry("700x500")
        admin_window.configure(bg="#f0f8ff")
        admin_window.transient(self.root)
        admin_window.grab_set()

        # Center the window using the custom method
        self.center_window(admin_window)

        AdminToolsPanel(admin_window, self.db)

    def authenticate(self):
        username = self.username_entry.get().strip().lower()
        password = self.password_entry.get()
        user_type = self.user_type.get()

        if not username or not password:
            messagebox.showerror("Error", "Please enter both username and password")
            return

        # Authenticate using database
        if self.db.authenticate_user(username, password, user_type):
            user_info = self.db.get_user_info(username)
            if user_info:
                self.root.destroy()  # Close login window
                # Launch the main application with the appropriate access level
                main_root = tk.Tk()
                app = ASLLearner(main_root, user_type, username, user_info['full_name'])
                main_root.mainloop()
        else:
            messagebox.showerror("Error", "Invalid username, password, or user type")


class RegistrationPanel:
    def __init__(self, window, login_app):
        self.window = window
        self.login_app = login_app
        self.create_registration_ui()

    def create_registration_ui(self):
        # Main frame
        main_frame = tk.Frame(self.window, bg="#f0f8ff", padx=30, pady=20)
        main_frame.pack(fill='both', expand=True)

        # Title
        title_label = tk.Label(main_frame, text="Create New Account", font=("Arial", 20, "bold"),
                               bg="#f0f8ff", fg="#2c3e50")
        title_label.pack(pady=(10, 20))

        # Registration form frame
        form_frame = tk.Frame(main_frame, bg="#f0f8ff")
        form_frame.pack(fill='x', pady=10)

        # Full Name
        tk.Label(form_frame, text="Full Name:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").grid(row=0, column=0, sticky='w', pady=8)
        self.full_name_entry = tk.Entry(form_frame, width=30, font=("Arial", 10),
                                        relief="flat", bg="#ecf0f1", highlightthickness=1,
                                        highlightcolor="#3498db", highlightbackground="#bdc3c7")
        self.full_name_entry.grid(row=0, column=1, padx=15, pady=8, sticky='ew')

        # Email
        tk.Label(form_frame, text="Email:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").grid(row=1, column=0, sticky='w', pady=8)
        self.email_entry = tk.Entry(form_frame, width=30, font=("Arial", 10),
                                    relief="flat", bg="#ecf0f1", highlightthickness=1,
                                    highlightcolor="#3498db", highlightbackground="#bdc3c7")
        self.email_entry.grid(row=1, column=1, padx=15, pady=8, sticky='ew')

        # Username
        tk.Label(form_frame, text="Username:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").grid(row=2, column=0, sticky='w', pady=8)
        self.username_entry = tk.Entry(form_frame, width=30, font=("Arial", 10),
                                       relief="flat", bg="#ecf0f1", highlightthickness=1,
                                       highlightcolor="#3498db", highlightbackground="#bdc3c7")
        self.username_entry.grid(row=2, column=1, padx=15, pady=8, sticky='ew')

        # Password
        tk.Label(form_frame, text="Password:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").grid(row=3, column=0, sticky='w', pady=8)
        self.password_entry = tk.Entry(form_frame, width=30, show="•", font=("Arial", 10),
                                       relief="flat", bg="#ecf0f1", highlightthickness=1,
                                       highlightcolor="#3498db", highlightbackground="#bdc3c7")
        self.password_entry.grid(row=3, column=1, padx=15, pady=8, sticky='ew')

        # Confirm Password
        tk.Label(form_frame, text="Confirm Password:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").grid(row=4, column=0, sticky='w', pady=8)
        self.confirm_password_entry = tk.Entry(form_frame, width=30, show="•", font=("Arial", 10),
                                               relief="flat", bg="#ecf0f1", highlightthickness=1,
                                               highlightcolor="#3498db", highlightbackground="#bdc3c7")
        self.confirm_password_entry.grid(row=4, column=1, padx=15, pady=8, sticky='ew')

        # User Type
        type_frame = tk.Frame(form_frame, bg="#f0f8ff")
        type_frame.grid(row=5, column=0, columnspan=2, pady=15, sticky='w')
        tk.Label(type_frame, text="Account Type:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").pack(side='left', padx=(0, 15))

        self.user_type = tk.StringVar(value="student")
        tk.Radiobutton(type_frame, text="Student", variable=self.user_type, value="student",
                       font=("Arial", 9), bg="#f0f8ff", fg="#2c3e50",
                       selectcolor="#e1f0fa").pack(side='left', padx=10)
        tk.Radiobutton(type_frame, text="Teacher", variable=self.user_type, value="teacher",
                       font=("Arial", 9), bg="#f0f8ff", fg="#2c3e50",
                       selectcolor="#e1f0fa").pack(side='left', padx=10)

        # Configure grid weights
        form_frame.columnconfigure(1, weight=1)

        # Password requirements label
        requirements_label = tk.Label(main_frame,
                                      text="Password must be at least 6 characters long",
                                      font=("Arial", 8), bg="#f0f8ff", fg="#7f8c8d")
        requirements_label.pack(pady=(0, 10))

        # Buttons frame
        button_frame = tk.Frame(main_frame, bg="#f0f8ff")
        button_frame.pack(pady=20)

        # Register button
        register_btn = tk.Button(button_frame, text="Create Account", command=self.register_user,
                                 bg="#27ae60", fg="white", font=("Arial", 11, "bold"),
                                 width=15, relief="flat", bd=0,
                                 activebackground="#219653", cursor="hand2")
        register_btn.pack(side='left', padx=10)

        # Cancel button
        cancel_btn = tk.Button(button_frame, text="Cancel", command=self.window.destroy,
                               bg="#95a5a6", fg="white", font=("Arial", 11, "bold"),
                               width=10, relief="flat", bd=0,
                               activebackground="#7f8c8d", cursor="hand2")
        cancel_btn.pack(side='left', padx=10)

        # Bind Enter key to registration
        self.window.bind('<Return>', lambda event: self.register_user())

    def register_user(self):
        """Register a new user"""
        # Get form data
        full_name = self.full_name_entry.get().strip()
        email = self.email_entry.get().strip().lower()
        username = self.username_entry.get().strip().lower()
        password = self.password_entry.get()
        confirm_password = self.confirm_password_entry.get()
        user_type = self.user_type.get()

        # Validate inputs
        if not all([full_name, email, username, password, confirm_password]):
            messagebox.showerror("Error", "Please fill in all fields")
            return

        if len(password) < 6:
            messagebox.showerror("Error", "Password must be at least 6 characters long")
            return

        if password != confirm_password:
            messagebox.showerror("Error", "Passwords do not match")
            return

        if not self.is_valid_email(email):
            messagebox.showerror("Error", "Please enter a valid email address")
            return

        if not self.is_valid_username(username):
            messagebox.showerror("Error", "Username can only contain letters, numbers, and underscores")
            return

        # Create user in database
        try:
            self.login_app.db.create_user(username, password, email, full_name, user_type)
            messagebox.showinfo("Success", f"Account created successfully!\n\n"
                                           f"Username: {username}\n"
                                           f"Account Type: {user_type.capitalize()}\n\n"
                                           f"You can now login with your new account.")
            self.window.destroy()
        except ValueError as e:
            messagebox.showerror("Error", str(e))

    def is_valid_email(self, email):
        """Basic email validation"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None

    def is_valid_username(self, username):
        """Username validation - alphanumeric and underscores only"""
        pattern = r'^[a-zA-Z0-9_]+$'
        return re.match(pattern, username) is not None


class AdminToolsPanel:
    def __init__(self, window, db):
        self.window = window
        self.db = db
        self.create_admin_ui()

    def create_admin_ui(self):
        # Main frame
        main_frame = tk.Frame(self.window, bg="#f0f8ff", padx=20, pady=20)
        main_frame.pack(fill='both', expand=True)

        # Title
        title_label = tk.Label(main_frame, text="User Management - Admin Tools",
                               font=("Arial", 16, "bold"), bg="#f0f8ff", fg="#2c3e50")
        title_label.pack(pady=(0, 20))

        # User list frame
        list_frame = tk.Frame(main_frame, bg="#f0f8ff")
        list_frame.pack(fill='both', expand=True, pady=10)

        # Treeview for displaying users
        columns = ("Username", "Email", "Full Name", "Type", "Created", "Last Login")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)

        # Configure columns
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor="w")

        self.tree.column("Username", width=120)
        self.tree.column("Email", width=150)
        self.tree.column("Full Name", width=120)
        self.tree.column("Type", width=80)
        self.tree.column("Created", width=100)
        self.tree.column("Last Login", width=120)

        # Scrollbar for treeview
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Buttons frame
        button_frame = tk.Frame(main_frame, bg="#f0f8ff")
        button_frame.pack(fill='x', pady=10)

        refresh_btn = tk.Button(button_frame, text="Refresh List", command=self.refresh_user_list,
                                bg="#3498db", fg="white", font=("Arial", 10, "bold"),
                                relief="flat", cursor="hand2")
        refresh_btn.pack(side='left', padx=5)

        delete_btn = tk.Button(button_frame, text="Delete Selected", command=self.delete_selected_user,
                               bg="#e74c3c", fg="white", font=("Arial", 10, "bold"),
                               relief="flat", cursor="hand2")
        delete_btn.pack(side='left', padx=5)

        close_btn = tk.Button(button_frame, text="Close", command=self.window.destroy,
                              bg="#95a5a6", fg="white", font=("Arial", 10, "bold"),
                              relief="flat", cursor="hand2")
        close_btn.pack(side='right', padx=5)

        # Load initial user list
        self.refresh_user_list()

    def refresh_user_list(self):
        """Refresh the user list in the treeview"""
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Get all users from database
        users = self.db.get_all_users()

        # Add users to treeview
        for user in users:
            self.tree.insert("", "end", values=(
                user['username'],
                user['email'],
                user['full_name'],
                user['user_type'],
                user['created_date'][:10] if user['created_date'] else 'N/A',
                user['last_login'][:19] if user['last_login'] else 'Never'
            ))

    def delete_selected_user(self):
        """Delete the selected user"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "Please select a user to delete")
            return

        item = selected[0]
        username = self.tree.item(item, "values")[0]

        # Prevent deletion of default accounts
        if username in ['teacher', 'student']:
            messagebox.showerror("Error", "Cannot delete default system accounts")
            return

        if messagebox.askyesno("Confirm Delete",
                               f"Are you sure you want to delete user '{username}'? This action cannot be undone."):
            try:
                self.db.delete_user(username)
                messagebox.showinfo("Success", f"User '{username}' has been deleted")
                self.refresh_user_list()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete user: {str(e)}")


class UploadLessonDialog:
    def __init__(self, parent, db, username):
        self.parent = parent
        self.db = db
        self.username = username
        self.file_path = None
        self.thumbnail_path = None
        self.create_dialog()

    def create_dialog(self):
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Upload New Lesson")
        self.dialog.geometry("600x600")  # Increased height for new button
        self.dialog.configure(bg="#f0f8ff")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

        # Center the dialog
        self.dialog.update_idletasks()
        width = self.dialog.winfo_width()
        height = self.dialog.winfo_height()
        x = (self.dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (height // 2)
        self.dialog.geometry('{}x{}+{}+{}'.format(600, 600, x, y))

        # Main frame
        main_frame = tk.Frame(self.dialog, bg="#f0f8ff", padx=20, pady=20)
        main_frame.pack(fill='both', expand=True)

        # Title
        title_label = tk.Label(main_frame, text="Upload New Lesson",
                               font=("Arial", 18, "bold"), bg="#f0f8ff", fg="#2c3e50")
        title_label.pack(pady=(0, 20))

        # Form frame
        form_frame = tk.Frame(main_frame, bg="#f0f8ff")
        form_frame.pack(fill='x', pady=10)

        # File selection
        file_frame = tk.Frame(form_frame, bg="#f0f8ff")
        file_frame.pack(fill='x', pady=10)

        tk.Label(file_frame, text="Select Video File:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").pack(anchor='w')

        file_btn_frame = tk.Frame(file_frame, bg="#f0f8ff")
        file_btn_frame.pack(fill='x', pady=5)

        self.file_label = tk.Label(file_btn_frame, text="No file selected",
                                   font=("Arial", 9), bg="#f0f8ff", fg="#7f8c8d", width=50, anchor='w')
        self.file_label.pack(side='left', padx=(0, 10))

        browse_btn = tk.Button(file_btn_frame, text="Browse", command=self.browse_file,
                               bg="#3498db", fg="white", font=("Arial", 9, "bold"),
                               relief="flat", cursor="hand2")
        browse_btn.pack(side='right')

        # Thumbnail selection (optional)
        thumb_frame = tk.Frame(form_frame, bg="#f0f8ff")
        thumb_frame.pack(fill='x', pady=10)

        tk.Label(thumb_frame, text="Thumbnail (Optional):", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").pack(anchor='w')

        thumb_btn_frame = tk.Frame(thumb_frame, bg="#f0f8ff")
        thumb_btn_frame.pack(fill='x', pady=5)

        self.thumb_label = tk.Label(thumb_btn_frame, text="No thumbnail selected",
                                    font=("Arial", 9), bg="#f0f8ff", fg="#7f8c8d", width=50, anchor='w')
        self.thumb_label.pack(side='left', padx=(0, 10))

        browse_thumb_btn = tk.Button(thumb_btn_frame, text="Browse", command=self.browse_thumbnail,
                                     bg="#3498db", fg="white", font=("Arial", 9, "bold"),
                                     relief="flat", cursor="hand2")
        browse_thumb_btn.pack(side='right')

        # Lesson title
        tk.Label(form_frame, text="Lesson Title:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").pack(anchor='w', pady=(10, 5))
        self.title_entry = tk.Entry(form_frame, width=50, font=("Arial", 10),
                                    relief="flat", bg="#ecf0f1", highlightthickness=1,
                                    highlightcolor="#3498db", highlightbackground="#bdc3c7")
        self.title_entry.pack(fill='x', pady=5)

        # Description
        tk.Label(form_frame, text="Description:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").pack(anchor='w', pady=(10, 5))
        self.desc_text = tk.Text(form_frame, width=50, height=4, font=("Arial", 10),
                                 relief="flat", bg="#ecf0f1", highlightthickness=1,
                                 highlightcolor="#3498db", highlightbackground="#bdc3c7")
        self.desc_text.pack(fill='x', pady=5)

        # Category
        cat_frame = tk.Frame(form_frame, bg="#f0f8ff")
        cat_frame.pack(fill='x', pady=10)

        tk.Label(cat_frame, text="Category:", font=("Arial", 10, "bold"),
                 bg="#f0f8ff", fg="#2c3e50").pack(side='left', padx=(0, 10))

        self.category_var = tk.StringVar(value="General")
        categories = ["General", "Beginner", "Intermediate", "Advanced", "Alphabet", "Numbers", "Phrases"]
        category_menu = ttk.Combobox(cat_frame, textvariable=self.category_var,
                                     values=categories, state="readonly", width=20)
        category_menu.pack(side='left')

        # NEW: Save in ASL Learner Frame button
        asl_frame = tk.Frame(form_frame, bg="#f0f8ff")
        asl_frame.pack(fill='x', pady=15)

        asl_save_btn = tk.Button(asl_frame, text="💾 Save in ASL Learner Frame",
                                command=self.save_in_asl_learner_frame,
                                bg="#9b59b6", fg="white", font=("Arial", 11, "bold"),
                                relief="flat", cursor="hand2", width=25, height=1,
                                activebackground="#8e44ad")
        asl_save_btn.pack(pady=5)

        asl_info_label = tk.Label(asl_frame,
                                 text="Save video directly to ASL Learner frame for quick access",
                                 font=("Arial", 8), bg="#f0f8ff", fg="#7f8c8d")
        asl_info_label.pack()

        # Buttons frame
        btn_frame = tk.Frame(main_frame, bg="#f0f8ff")
        btn_frame.pack(fill='x', pady=20)

        # Save button - saves video to folder without database entry
        save_btn = tk.Button(btn_frame, text="Save Video Only", command=self.save_video_only,
                             bg="#f39c12", fg="white", font=("Arial", 10, "bold"),
                             relief="flat", cursor="hand2", width=15)
        save_btn.pack(side='left', padx=5)

        # Upload button - saves to folder AND database
        upload_btn = tk.Button(btn_frame, text="Upload Lesson", command=self.upload_lesson,
                               bg="#27ae60", fg="white", font=("Arial", 11, "bold"),
                               relief="flat", cursor="hand2", width=15)
        upload_btn.pack(side='left', padx=5)

        cancel_btn = tk.Button(btn_frame, text="Cancel", command=self.dialog.destroy,
                               bg="#95a5a6", fg="white", font=("Arial", 11, "bold"),
                               relief="flat", cursor="hand2", width=10)
        cancel_btn.pack(side='right', padx=5)

    def browse_file(self):
        """Browse for video file"""
        filetypes = [
            ("Video files", "*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm"),
            ("All files", "*.*")
        ]
        filename = filedialog.askopenfilename(title="Select Video File", filetypes=filetypes)
        if filename:
            self.file_path = filename
            self.file_label.config(text=os.path.basename(filename))

            # Auto-generate title from filename if title is empty
            if not self.title_entry.get():
                title = os.path.splitext(os.path.basename(filename))[0]
                title = title.replace('_', ' ').replace('-', ' ').title()
                self.title_entry.insert(0, title)

    def browse_thumbnail(self):
        """Browse for thumbnail image"""
        filetypes = [
            ("Image files", "*.jpg *.jpeg *.png *.bmp *.gif"),
            ("All files", "*.*")
        ]
        filename = filedialog.askopenfilename(title="Select Thumbnail Image", filetypes=filetypes)
        if filename:
            self.thumbnail_path = filename
            self.thumb_label.config(text=os.path.basename(filename))

    def save_in_asl_learner_frame(self):
        """Save video specifically in ASL Learner frame directory"""
        if not self.file_path:
            messagebox.showerror("Error", "Please select a video file first")
            return

        try:
            # Create asl_learner_frame directory if it doesn't exist
            asl_frame_dir = "asl_learner_frame"
            os.makedirs(asl_frame_dir, exist_ok=True)

            # Generate unique filename
            original_name = os.path.basename(self.file_path)
            file_ext = os.path.splitext(original_name)[1]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Use title if available, otherwise use original name
            if self.title_entry.get().strip():
                safe_title = "".join(
                    c for c in self.title_entry.get().strip() if c.isalnum() or c in (' ', '-', '_')).rstrip()
                new_filename = f"asl_frame_{safe_title}_{timestamp}{file_ext}"
            else:
                new_filename = f"asl_frame_video_{timestamp}{file_ext}"

            new_filepath = os.path.join(asl_frame_dir, new_filename)

            # Copy file to asl_learner_frame directory
            shutil.copy2(self.file_path, new_filepath)

            messagebox.showinfo("Success",
                                f"Video saved in ASL Learner Frame!\n\n"
                                f"Saved to: {asl_frame_dir}\n"
                                f"Filename: {new_filename}\n\n"
                                f"The video is now available in the ASL Learner frame for quick access.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save video in ASL Learner frame: {str(e)}")

    def save_video_only(self):
        """Save video to folder without database entry"""
        if not self.file_path:
            messagebox.showerror("Error", "Please select a video file")
            return

        try:
            # Create saved_videos directory if it doesn't exist
            saved_videos_dir = "saved_videos"
            os.makedirs(saved_videos_dir, exist_ok=True)

            # Generate unique filename
            original_name = os.path.basename(self.file_path)
            file_ext = os.path.splitext(original_name)[1]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Use title if available, otherwise use original name
            if self.title_entry.get().strip():
                safe_title = "".join(
                    c for c in self.title_entry.get().strip() if c.isalnum() or c in (' ', '-', '_')).rstrip()
                new_filename = f"{safe_title}_{timestamp}{file_ext}"
            else:
                new_filename = f"saved_video_{timestamp}{file_ext}"

            new_filepath = os.path.join(saved_videos_dir, new_filename)

            # Copy file to saved_videos directory
            shutil.copy2(self.file_path, new_filepath)

            messagebox.showinfo("Success",
                                f"Video saved successfully!\n\nSaved to: {saved_videos_dir}\nFilename: {new_filename}")

            # Optionally keep the dialog open for further actions
            # self.dialog.destroy()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save video: {str(e)}")

    def upload_lesson(self):
        """Upload the lesson to the system (save to folder AND database)"""
        if not self.file_path:
            messagebox.showerror("Error", "Please select a video file")
            return

        if not self.title_entry.get().strip():
            messagebox.showerror("Error", "Please enter a lesson title")
            return

        try:
            # Create uploads directory if it doesn't exist
            uploads_dir = "uploaded_lessons"
            os.makedirs(uploads_dir, exist_ok=True)
            thumbnails_dir = os.path.join(uploads_dir, "thumbnails")
            os.makedirs(thumbnails_dir, exist_ok=True)

            # Generate unique filename
            original_name = os.path.basename(self.file_path)
            file_ext = os.path.splitext(original_name)[1]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_filename = f"lesson_{timestamp}{file_ext}"
            new_filepath = os.path.join(uploads_dir, new_filename)

            # Copy file to uploads directory
            shutil.copy2(self.file_path, new_filepath)
            file_size = os.path.getsize(new_filepath)

            # Process thumbnail if provided
            final_thumbnail_path = None
            if self.thumbnail_path:
                thumb_ext = os.path.splitext(self.thumbnail_path)[1]
                thumb_filename = f"thumb_{timestamp}{thumb_ext}"
                final_thumbnail_path = os.path.join(thumbnails_dir, thumb_filename)
                shutil.copy2(self.thumbnail_path, final_thumbnail_path)

            # Get video duration
            duration = self.get_video_duration(new_filepath)

            # Add to database
            self.db.add_uploaded_lesson(
                filename=new_filename,
                original_name=original_name,
                file_path=new_filepath,
                file_size=file_size,
                file_type=file_ext[1:].upper(),
                title=self.title_entry.get().strip(),
                description=self.desc_text.get("1.0", "end-1c").strip(),
                category=self.category_var.get(),
                uploaded_by=self.username,
                duration=duration,
                thumbnail_path=final_thumbnail_path
            )

            messagebox.showinfo("Success", "Lesson uploaded successfully!")
            self.dialog.destroy()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to upload lesson: {str(e)}")

    def get_video_duration(self, filepath):
        """Get duration of video file in seconds"""
        try:
            cap = cv2.VideoCapture(filepath)
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            duration = frame_count / fps if fps > 0 else 0
            cap.release()
            return int(duration)
        except:
            return 0


class VideoItem:
    def __init__(self, parent, video_data, on_select_callback, db=None):
        self.parent = parent
        self.video_data = video_data
        self.on_select_callback = on_select_callback
        self.db = db
        self.frame = None
        self.thumbnail = None
        self.create_widget()

    def create_widget(self):
        # Main frame for video item
        self.frame = tk.Frame(self.parent, bg="white", relief="raised", bd=1)
        self.frame.pack(fill='x', pady=5, padx=5)

        # Thumbnail
        thumb_frame = tk.Frame(self.frame, bg="white", width=320, height=180)
        thumb_frame.pack_propagate(False)
        thumb_frame.pack(side='left', padx=5, pady=5)

        try:
            # Get thumbnail path
            thumb_path = None
            if 'thumbnail_path' in self.video_data and self.video_data['thumbnail_path'] and os.path.exists(
                    self.video_data['thumbnail_path']):
                thumb_path = self.video_data['thumbnail_path']
            elif 'file_path' in self.video_data and os.path.exists(self.video_data['file_path']):
                thumb_path = self.video_data['file_path']

            if thumb_path and os.path.exists(thumb_path):
                if thumb_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                    # It's an image thumbnail
                    img = Image.open(thumb_path)
                else:
                    # It's a video - get first frame
                    cap = cv2.VideoCapture(thumb_path)
                    ret, frame = cap.read()
                    if ret:
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame)
                    else:
                        img = Image.new('RGB', (320, 180), color='#2c3e50')
                    cap.release()

                img = img.resize((320, 180), Image.Resampling.LANCZOS)
                self.thumbnail = ImageTk.PhotoImage(image=img)

                thumb_label = tk.Label(thumb_frame, image=self.thumbnail, cursor="hand2", bg="black")
                thumb_label.pack(fill='both', expand=True)
                thumb_label.bind("<Button-1>", lambda e: self.on_select_callback(self.video_data['file_path']))

            else:
                # Create default thumbnail
                img = Image.new('RGB', (320, 180), color='#2c3e50')
                self.thumbnail = ImageTk.PhotoImage(image=img)
                thumb_label = tk.Label(thumb_frame, image=self.thumbnail, cursor="hand2", bg="black")
                thumb_label.pack(fill='both', expand=True)
                thumb_label.bind("<Button-1>", lambda e: self.on_select_callback(self.video_data['file_path']))

        except Exception as e:
            print(f"Error creating thumbnail for {self.video_data.get('file_path', 'unknown')}: {e}")
            # Create default thumbnail on error
            img = Image.new('RGB', (320, 180), color='#2c3e50')
            self.thumbnail = ImageTk.PhotoImage(image=img)
            thumb_label = tk.Label(thumb_frame, image=self.thumbnail, cursor="hand2", bg="black")
            thumb_label.pack(fill='both', expand=True)
            thumb_label.bind("<Button-1>", lambda e: self.on_select_callback(self.video_data['file_path']))

        # Video info
        info_frame = tk.Frame(self.frame, bg="white")
        info_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Title
        title_text = self.video_data.get('title',
                                         os.path.basename(self.video_data.get('file_path', 'Unknown Video'))
                                         .replace('recording_', '')
                                         .replace('saved_video_', '')
                                         .replace('lesson_', '')
                                         .replace('.avi', '')
                                         .replace('.mp4', '')
                                         .replace('_', ' ')
                                         .title())

        title_label = tk.Label(info_frame, text=title_text,
                               font=("Arial", 14, "bold"),
                               bg="white", fg="#2c3e50",
                               anchor='w', justify='left')
        title_label.pack(anchor='w', pady=(0, 5))

        # Description
        if 'description' in self.video_data and self.video_data['description']:
            desc_text = self.video_data['description'][:100] + "..." if len(self.video_data['description']) > 100 else \
            self.video_data['description']
            desc_label = tk.Label(info_frame, text=desc_text,
                                  font=("Arial", 10),
                                  bg="white", fg="#7f8c8d",
                                  anchor='w', justify='left', wraplength=400)
            desc_label.pack(anchor='w', pady=(0, 5))

        # Metadata
        meta_frame = tk.Frame(info_frame, bg="white")
        meta_frame.pack(anchor='w', pady=(0, 5))

        # Uploader/Author
        author = self.video_data.get('uploaded_by', 'System')
        author_label = tk.Label(meta_frame, text=author,
                                font=("Arial", 10, "bold"),
                                bg="white", fg="#3498db")
        author_label.pack(side='left', padx=(0, 10))

        # Views (for uploaded lessons)
        if 'views' in self.video_data:
            views_text = f"{self.video_data['views']} views"
            views_label = tk.Label(meta_frame, text=views_text,
                                   font=("Arial", 9),
                                   bg="white", fg="#7f8c8d")
            views_label.pack(side='left', padx=(0, 10))

        # Duration
        duration = self.video_data.get('duration', 0)
        if duration:
            duration_text = f"{duration // 60}:{duration % 60:02d}"
        else:
            # Try to get duration from file
            try:
                if 'file_path' in self.video_data and os.path.exists(self.video_data['file_path']):
                    cap = cv2.VideoCapture(self.video_data['file_path'])
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    duration = int(frame_count / fps) if fps > 0 else 0
                    duration_text = f"{duration // 60}:{duration % 60:02d}"
                    cap.release()
                else:
                    duration_text = "N/A"
            except:
                duration_text = "N/A"

        duration_label = tk.Label(meta_frame, text=duration_text,
                                  font=("Arial", 9),
                                  bg="white", fg="#7f8c8d")
        duration_label.pack(side='left', padx=(0, 10))

        # File size
        file_size = self.video_data.get('file_size', 0)
        if not file_size and 'file_path' in self.video_data and os.path.exists(self.video_data['file_path']):
            try:
                file_size = os.path.getsize(self.video_data['file_path'])
            except:
                file_size = 0

        size_mb = file_size / (1024 * 1024) if file_size else 0
        size_label = tk.Label(meta_frame, text=f"{size_mb:.1f} MB",
                              font=("Arial", 9),
                              bg="white", fg="#7f8c8d")
        size_label.pack(side='left', padx=(0, 10))

        # Upload date or file modification date
        upload_date = self.video_data.get('upload_date', '')
        if not upload_date and 'file_path' in self.video_data and os.path.exists(self.video_data['file_path']):
            try:
                upload_date = datetime.fromtimestamp(os.path.getmtime(self.video_data['file_path'])).strftime(
                    "%Y-%m-%d")
            except:
                upload_date = "Unknown"

        date_label = tk.Label(meta_frame, text=upload_date,
                              font=("Arial", 9),
                              bg="white", fg="#7f8c8d")
        date_label.pack(side='left')

        # Category badge
        if 'category' in self.video_data and self.video_data['category']:
            category_frame = tk.Frame(info_frame, bg="white")
            category_frame.pack(anchor='w', pady=(5, 0))

            category_label = tk.Label(category_frame, text=self.video_data['category'],
                                      font=("Arial", 8, "bold"),
                                      bg="#e74c3c", fg="white",
                                      padx=5, pady=2)
            category_label.pack(side='left')

        # Video type badge
        video_type = self.video_data.get('type', 'unknown')
        type_colors = {
            'uploaded': '#27ae60',
            'demonstration': '#3498db',
            'practice': '#9b59b6',
            'saved': '#f39c12',
            'asl_frame': '#9b59b6'  # Purple color for ASL frame videos
        }
        type_frame = tk.Frame(info_frame, bg="white")
        type_frame.pack(anchor='w', pady=(5, 0))

        type_label = tk.Label(type_frame, text=video_type.title(),
                              font=("Arial", 8, "bold"),
                              bg=type_colors.get(video_type, '#95a5a6'), fg="white",
                              padx=5, pady=2)
        type_label.pack(side='left')

        # Make the whole item clickable
        for widget in [self.frame, info_frame]:
            widget.bind("<Button-1>", lambda e, path=self.video_data['file_path']: self.on_select_callback(path))
            for child in widget.winfo_children():
                if isinstance(child, tk.Frame):
                    for grandchild in child.winfo_children():
                        grandchild.bind("<Button-1>",
                                        lambda e, path=self.video_data['file_path']: self.on_select_callback(path))
                else:
                    child.bind("<Button-1>", lambda e, path=self.video_data['file_path']: self.on_select_callback(path))


class ASLLearner:
    def __init__(self, root, user_type, username, full_name="User"):
        self.root = root
        self.user_type = user_type  # "teacher" or "student"
        self.username = username
        self.full_name = full_name
        self.root.title(f"ASL Learner - {user_type.capitalize()} Mode - Welcome {full_name}")
        self.root.geometry("1400x900")
        self.root.configure(bg="#ecf0f1")

        # Initialize database
        self.db = DatabaseManager()

        # Set application icon (if available)
        try:
            self.root.iconbitmap("asl_icon.ico")
        except:
            pass

        # Recording variables
        self.recording = False
        self.audio_thread = None
        self.audio_filename = ""
        self.current_frame = 0
        self.fps = 20
        self.total_frames = 0
        self.cap = None
        self.playing = False
        self.paused = False
        self.volume = 2.0  # Default amplified volume

        # Video gallery variables
        self.video_files = []
        self.thumbnails = []
        self.current_video_index = -1
        self.all_videos = []

        # Screen recording variables
        self.screen_recording = False
        self.screen_out = None
        self.recording_thread = None

        # Create folders
        for folder in ["recordings_demonstrations", "recordings_practice", "uploaded_lessons",
                       "uploaded_lessons/thumbnails", "saved_videos", "asl_learner_frame"]:
            os.makedirs(folder, exist_ok=True)

        # Header
        self.header = tk.Frame(root, bg="#2c3e50", height=60)
        self.header.pack(fill='x', side='top')
        self.header.pack_propagate(False)

        # Left side - Title
        title = tk.Label(self.header, text="ASL Learner", font=("Arial", 20, "bold"),
                         fg="white", bg="#2c3e50")
        title.pack(side='left', padx=20)

        # Right side - User info and logout button
        user_frame = tk.Frame(self.header, bg="#2c3e50")
        user_frame.pack(side='right', padx=20)

        user_label = tk.Label(user_frame, text=f"Welcome, {full_name} ({user_type})",
                              font=("Arial", 10), fg="#ecf0f1", bg="#2c3e50")
        user_label.pack(side='left', padx=(0, 15))

        # Logout button
        self.logout_btn = tk.Button(user_frame, text="Logout", command=self.logout,
                                    bg="#e74c3c", fg="white", font=("Arial", 10, "bold"),
                                    relief="flat", cursor="hand2", activebackground="#c0392b",
                                    padx=10, pady=2)
        self.logout_btn.pack(side='right')

        # Notebook for tabs
        style = ttk.Style()
        style.configure("TNotebook", background="#ecf0f1", borderwidth=0)
        style.configure("TNotebook.Tab", font=("Arial", 11, "bold"), padding=[15, 5])
        style.map("TNotebook.Tab", background=[("selected", "#3498db")],
                  foreground=[("selected", "white")])

        self.notebook = ttk.Notebook(root, style="TNotebook")
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # Tabs - different for teacher and student
        if self.user_type == "teacher":
            self.record_frame = ttk.Frame(self.notebook)
            self.gallery_frame = ttk.Frame(self.notebook)
            self.player_frame = ttk.Frame(self.notebook)
            self.notebook.add(self.record_frame, text='Create Lessons')
            self.notebook.add(self.gallery_frame, text='ASL Library')
            self.notebook.add(self.player_frame, text='Player')

            # Setup all tabs for teacher
            self.setup_record_tab()
            self.setup_gallery_tab()
            self.setup_player_tab()
        else:
            # Student only gets gallery and player tabs
            self.gallery_frame = ttk.Frame(self.notebook)
            self.player_frame = ttk.Frame(self.notebook)
            self.notebook.add(self.gallery_frame, text='ASL Library')
            self.notebook.add(self.player_frame, text='Player')

            # Setup only gallery and player for student
            self.setup_gallery_tab()
            self.setup_player_tab()

            # Add ASL button for student
            self.add_student_asl_button()

        self.load_all_videos()

    def logout(self):
        """Log out and return to login screen"""
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            self.root.destroy()
            login_root = tk.Tk()
            login_app = LoginPage(login_root)
            login_root.mainloop()

    def add_student_asl_button(self):
        # Add a button to run ASL for students
        asl_frame = tk.Frame(self.gallery_frame, bg="#ecf0f1")
        asl_frame.pack(fill='x', pady=10)

        asl_btn = tk.Button(asl_frame, text="Practice ASL", bg="#3498db", fg="white",
                            command=lambda: self.run_script_normally("asl.py"),
                            font=("Arial", 12, "bold"), relief="flat", height=1,
                            activebackground="#2980b9", cursor="hand2")
        asl_btn.pack(pady=10, ipadx=20, ipady=8)

        label = tk.Label(asl_frame, text="Click to practice American Sign Language",
                         font=("Arial", 10), bg="#ecf0f1", fg="#7f8c8d")
        label.pack(pady=(0, 10))

    # ---------------- Helpers ---------------- #
    def generate_filename(self, folder, ext=".avi"):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return os.path.join(folder, f"recording_{timestamp}{ext}")

    # ---------------- Record Tab ---------------- #
    def setup_record_tab(self):
        # Only teachers have access to the record tab
        if self.user_type != "teacher":
            return

        # Configure style for teacher tab
        style = ttk.Style()
        style.configure("Teacher.TFrame", background="#ecf0f1")
        self.record_frame.configure(style="Teacher.TFrame")

        title = tk.Label(self.record_frame, text="Create ASL Lesson Content",
                         font=("Arial", 18, "bold"), bg="#ecf0f1", fg="#2c3e50")
        title.pack(pady=20)

        # Button container
        btn_container = tk.Frame(self.record_frame, bg="#ecf0f1")
        btn_container.pack(pady=10)

        # ASL Application section only
        asl_frame = tk.Frame(btn_container, bg="#ecf0f1")
        asl_frame.pack(pady=10)

        tk.Label(asl_frame, text="ASL Application", font=("Arial", 14, "bold"),
                 bg="#ecf0f1", fg="#2c3e50").pack(pady=(0, 15))

        # Single row for ASL buttons
        asl_btn_frame = tk.Frame(asl_frame, bg="#ecf0f1")
        asl_btn_frame.pack(pady=10)

        asl_record_btn = tk.Button(asl_btn_frame, text="Record ASL Lesson", bg="#3498db", fg="white",
                                   command=self.record_asl_lesson,
                                   font=("Arial", 11, "bold"), width=20, relief="flat",
                                   activebackground="#2980b9", cursor="hand2")
        asl_record_btn.pack(side='left', padx=10, pady=8)

        asl_run_btn = tk.Button(asl_btn_frame, text="Run ASL Application", bg="#9b59b6", fg="white",
                                command=lambda: self.run_script_normally("asl.py"),
                                font=("Arial", 11, "bold"), width=20, relief="flat",
                                activebackground="#8e44ad", cursor="hand2")
        asl_run_btn.pack(side='left', padx=10, pady=8)

        # Recording indicator
        self.rec_indicator = tk.Label(self.record_frame, text="● RECORDING", fg="#e74c3c",
                                      font=("Arial", 14, "bold"), bg="#ecf0f1")
        self.rec_indicator.pack(pady=10)
        self.rec_indicator.pack_forget()

        # Instructions
        instructions = tk.Label(self.record_frame,
                                text="Create demonstration videos for your students to practice with.\n"
                                     "Use 'Record ASL Lesson' to create lessons using the ASL application.\n"
                                     "The recording will automatically save when you close the ASL application window.",
                                font=("Arial", 10), bg="#ecf0f1", fg="#7f8c8d", justify="center")
        instructions.pack(side='bottom', pady=20)

    def record_asl_lesson(self):
        """Record the ASL application window/frame and save when closed"""
        if self.user_type != "teacher":
            messagebox.showerror("Access Denied", "Only teachers can record lessons.")
            return

        if not os.path.exists("asl.py"):
            messagebox.showerror("Error", "asl.py not found!")
            return

        # Start ASL application
        self.asl_process = subprocess.Popen([sys.executable, "asl.py", "--fullscreen"])

        # Wait a moment for the window to appear
        time.sleep(2)

        # Start screen recording
        self.start_screen_recording()

        # Show recording indicator
        self.rec_indicator.pack()

        # Monitor the ASL process
        threading.Thread(target=self.monitor_asl_process, daemon=True).start()

    def start_screen_recording(self):
        """Start recording the screen"""
        try:
            # Find ASL window
            asl_window = None
            for window in gw.getWindowsWithTitle(''):
                if 'asl' in window.title.lower() or 'sign' in window.title.lower():
                    asl_window = window
                    break

            if asl_window:
                # Record specific window
                screen_size = (asl_window.width, asl_window.height)
                screen_pos = (asl_window.left, asl_window.top)
            else:
                # Record full screen as fallback
                screen_size = (pyautogui.size().width, pyautogui.size().height)
                screen_pos = (0, 0)

            # Generate filename
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"recordings_demonstrations/asl_lesson_{timestamp}.avi"

            # Define the codec and create VideoWriter object
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            self.screen_out = cv2.VideoWriter(filename, fourcc, 20.0, screen_size)

            self.screen_recording = True

            # Start recording in a separate thread
            self.recording_thread = threading.Thread(target=self.record_screen,
                                                     args=(screen_pos, screen_size),
                                                     daemon=True)
            self.recording_thread.start()

        except Exception as e:
            messagebox.showerror("Recording Error", f"Failed to start screen recording: {str(e)}")
            self.screen_recording = False

    def record_screen(self, screen_pos, screen_size):
        """Record the screen continuously"""
        try:
            while self.screen_recording:
                # Capture screen
                screenshot = pyautogui.screenshot(region=(screen_pos[0], screen_pos[1],
                                                          screen_size[0], screen_size[1]))
                frame = np.array(screenshot)
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

                # Write the frame
                self.screen_out.write(frame)

                # Small delay to control frame rate
                time.sleep(0.05)  # ~20 FPS

        except Exception as e:
            print(f"Screen recording error: {e}")

    def stop_screen_recording(self):
        """Stop screen recording and save file"""
        if self.screen_recording:
            self.screen_recording = False

            # Wait for recording thread to finish
            if self.recording_thread and self.recording_thread.is_alive():
                self.recording_thread.join(timeout=2.0)

            # Release the video writer
            if self.screen_out:
                self.screen_out.release()
                self.screen_out = None

            # Hide recording indicator
            self.rec_indicator.pack_forget()

            # Reload videos to show the new recording
            self.load_all_videos()

    def monitor_asl_process(self):
        """Monitor the ASL process and stop recording when it closes"""
        try:
            # Wait for the process to finish
            self.asl_process.wait()

            # Stop recording
            self.stop_screen_recording()

            # Show success message
            messagebox.showinfo("Recording Complete",
                                "ASL lesson recording has been saved successfully!")

        except Exception as e:
            print(f"Error monitoring ASL process: {e}")
            self.stop_screen_recording()

    def run_script_normally(self, script_name):
        """Runs ASL without recording."""
        if not os.path.exists(script_name):
            messagebox.showerror("Error", f"{script_name} not found!")
            return
        subprocess.Popen([sys.executable, script_name, "--fullscreen"])

    # ---------------- Gallery Tab ---------------- #
    def setup_gallery_tab(self):
        # Configure style for gallery
        style = ttk.Style()
        style.configure("Gallery.TFrame", background="#ecf0f1")
        self.gallery_frame.configure(style="Gallery.TFrame")

        # Title and controls frame
        title_frame = tk.Frame(self.gallery_frame, bg="#ecf0f1")
        title_frame.pack(fill='x', pady=10, padx=20)

        # Title
        title_text = "ASL Lesson Library - All Videos"
        title = tk.Label(title_frame, text=title_text, font=("Arial", 20, "bold"),
                         bg="#ecf0f1", fg="#2c3e50")
        title.pack(side='left')

        # Upload button for teachers
        if self.user_type == "teacher":
            upload_btn = tk.Button(title_frame, text="📁 Upload New Lesson",
                                   command=self.show_upload_dialog,
                                   bg="#27ae60", fg="white", font=("Arial", 12, "bold"),
                                   relief="flat", height=1, cursor="hand2",
                                   activebackground="#219653", padx=20, pady=10)
            upload_btn.pack(side='right', padx=10)

        # Refresh button
        refresh_btn = tk.Button(title_frame, text="🔄 Refresh",
                                command=self.load_all_videos,
                                bg="#3498db", fg="white", font=("Arial", 11, "bold"),
                                relief="flat", cursor="hand2",
                                activebackground="#2980b9", padx=15, pady=8)
        refresh_btn.pack(side='right', padx=5)

        # Search frame
        search_frame = tk.Frame(self.gallery_frame, bg="#ecf0f1")
        search_frame.pack(fill='x', pady=10, padx=20)

        tk.Label(search_frame, text="Search:", font=("Arial", 11, "bold"),
                 bg="#ecf0f1", fg="#2c3e50").pack(side='left', padx=(0, 10))

        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var, width=40,
                                     font=("Arial", 11), relief="solid", bd=1)
        self.search_entry.pack(side='left', padx=(0, 10))
        self.search_entry.bind('<KeyRelease>', self.filter_videos)

        # Filter by category
        tk.Label(search_frame, text="Category:", font=("Arial", 11, "bold"),
                 bg="#ecf0f1", fg="#2c3e50").pack(side='left', padx=(20, 10))

        self.category_var = tk.StringVar(value="All")
        categories = ["All", "General", "Beginner", "Intermediate", "Advanced", "Alphabet", "Numbers", "Phrases"]
        category_menu = ttk.Combobox(search_frame, textvariable=self.category_var,
                                     values=categories, state="readonly", width=15)
        category_menu.pack(side='left', padx=(0, 10))
        category_menu.bind('<<ComboboxSelected>>', self.filter_videos)

        # Sort options
        tk.Label(search_frame, text="Sort by:", font=("Arial", 11, "bold"),
                 bg="#ecf0f1", fg="#2c3e50").pack(side='left', padx=(20, 10))

        self.sort_var = tk.StringVar(value="Newest")
        sort_menu = ttk.Combobox(search_frame, textvariable=self.sort_var,
                                 values=["Newest", "Oldest", "Title A-Z", "Title Z-A", "Most Views"],
                                 state="readonly", width=12)
        sort_menu.pack(side='left', padx=(0, 10))
        sort_menu.bind('<<ComboboxSelected>>', self.filter_videos)

        # Video count label
        self.video_count_label = tk.Label(search_frame, text="Loading videos...",
                                          font=("Arial", 10), bg="#ecf0f1", fg="#7f8c8d")
        self.video_count_label.pack(side='right')

        # Canvas and scrollbar for gallery
        canvas_frame = tk.Frame(self.gallery_frame, bg="#ecf0f1")
        canvas_frame.pack(fill='both', expand=True, padx=20, pady=10)

        self.canvas = tk.Canvas(canvas_frame, bg="#ecf0f1", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.scrollbar.pack(side="right", fill="y")

        # Bind mousewheel to canvas
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def show_upload_dialog(self):
        """Show the upload lesson dialog"""
        UploadLessonDialog(self.root, self.db, self.username)

    def load_all_videos(self):
        """Load all videos from all sources into a unified YouTube-style list"""
        self.all_videos = []

        # Load uploaded lessons from database
        try:
            uploaded_lessons = self.db.get_uploaded_lessons()
            for lesson in uploaded_lessons:
                # Verify the file exists before adding
                if os.path.exists(lesson['file_path']):
                    lesson['type'] = 'uploaded'
                    lesson['source'] = 'Uploaded Lesson'
                    self.all_videos.append(lesson)
                else:
                    print(f"Uploaded lesson file not found: {lesson['file_path']}")
        except Exception as e:
            print(f"Error loading uploaded lessons: {e}")

        # Load recorded demonstrations (including screen recordings)
        demo_folder = "recordings_demonstrations"
        if os.path.exists(demo_folder):
            video_extensions = ['*.avi', '*.mp4', '*.mov', '*.mkv', '*.wmv', '*.flv', '*.webm']
            for ext in video_extensions:
                try:
                    for video_file in glob.glob(os.path.join(demo_folder, ext)):
                        if os.path.exists(video_file):
                            video_data = {
                                'file_path': video_file,
                                'title': os.path.basename(video_file)
                                .replace('recording_', '')
                                .replace('asl_lesson_', 'ASL Lesson ')
                                .replace('.avi', '')
                                .replace('.mp4', '')
                                .replace('_', ' ')
                                .title(),
                                'type': 'demonstration',
                                'source': 'Demonstration',
                                'uploaded_by': 'System',
                                'file_size': os.path.getsize(video_file),
                                'upload_date': datetime.fromtimestamp(os.path.getmtime(video_file)).strftime("%Y-%m-%d")
                            }
                            self.all_videos.append(video_data)
                except Exception as e:
                    print(f"Error loading demonstration videos with extension {ext}: {e}")

        # Load practice sessions
        practice_folder = "recordings_practice"
        if os.path.exists(practice_folder):
            for ext in video_extensions:
                try:
                    for video_file in glob.glob(os.path.join(practice_folder, ext)):
                        if os.path.exists(video_file):
                            video_data = {
                                'file_path': video_file,
                                'title': os.path.basename(video_file)
                                .replace('recording_', '')
                                .replace('.avi', '')
                                .replace('.mp4', '')
                                .replace('_', ' ')
                                .title(),
                                'type': 'practice',
                                'source': 'Practice Session',
                                'uploaded_by': 'System',
                                'file_size': os.path.getsize(video_file),
                                'upload_date': datetime.fromtimestamp(os.path.getmtime(video_file)).strftime("%Y-%m-%d")
                            }
                            self.all_videos.append(video_data)
                except Exception as e:
                    print(f"Error loading practice videos with extension {ext}: {e}")

        # Load saved videos
        saved_folder = "saved_videos"
        if os.path.exists(saved_folder):
            for ext in video_extensions:
                try:
                    for video_file in glob.glob(os.path.join(saved_folder, ext)):
                        if os.path.exists(video_file):
                            video_data = {
                                'file_path': video_file,
                                'title': os.path.basename(video_file)
                                .replace('saved_video_', '')
                                .replace('.mp4', '')
                                .replace('.avi', '')
                                .replace('_', ' ')
                                .title(),
                                'type': 'saved',
                                'source': 'Saved Video',
                                'uploaded_by': 'System',
                                'file_size': os.path.getsize(video_file),
                                'upload_date': datetime.fromtimestamp(os.path.getmtime(video_file)).strftime("%Y-%m-%d")
                            }
                            self.all_videos.append(video_data)
                except Exception as e:
                    print(f"Error loading saved videos with extension {ext}: {e}")

        # Load ASL Learner Frame videos
        asl_frame_folder = "asl_learner_frame"
        if os.path.exists(asl_frame_folder):
            for ext in video_extensions:
                try:
                    for video_file in glob.glob(os.path.join(asl_frame_folder, ext)):
                        if os.path.exists(video_file):
                            video_data = {
                                'file_path': video_file,
                                'title': os.path.basename(video_file)
                                .replace('asl_frame_', 'ASL Frame: ')
                                .replace('.mp4', '')
                                .replace('.avi', '')
                                .replace('_', ' ')
                                .title(),
                                'type': 'asl_frame',
                                'source': 'ASL Learner Frame',
                                'uploaded_by': 'System',
                                'file_size': os.path.getsize(video_file),
                                'upload_date': datetime.fromtimestamp(os.path.getmtime(video_file)).strftime("%Y-%m-%d")
                            }
                            self.all_videos.append(video_data)
                except Exception as e:
                    print(f"Error loading ASL frame videos with extension {ext}: {e}")

        # Update video count
        self.video_count_label.config(text=f"Total Videos: {len(self.all_videos)}")

        # Apply current filters
        self.filter_videos()

    def filter_videos(self, event=None):
        """Filter and sort videos based on search and category filters"""
        search_term = self.search_var.get().lower()
        category_filter = self.category_var.get()
        sort_by = self.sort_var.get()

        # Filter videos
        filtered_videos = []
        for video in self.all_videos:
            # Search filter
            title = video.get('title', '').lower()
            description = video.get('description', '').lower()
            author = video.get('uploaded_by', '').lower()

            matches_search = (search_term in title or
                              search_term in description or
                              search_term in author)

            # Category filter
            video_category = video.get('category', 'General')
            matches_category = (category_filter == "All" or
                                video_category == category_filter)

            if matches_search and matches_category:
                filtered_videos.append(video)

        # Sort videos
        if sort_by == "Newest":
            filtered_videos.sort(key=lambda x: x.get('upload_date', ''), reverse=True)
        elif sort_by == "Oldest":
            filtered_videos.sort(key=lambda x: x.get('upload_date', ''))
        elif sort_by == "Title A-Z":
            filtered_videos.sort(key=lambda x: x.get('title', '').lower())
        elif sort_by == "Title Z-A":
            filtered_videos.sort(key=lambda x: x.get('title', '').lower(), reverse=True)
        elif sort_by == "Most Views":
            filtered_videos.sort(key=lambda x: x.get('views', 0), reverse=True)

        # Display filtered videos
        self.display_videos(filtered_videos)

    def display_videos(self, videos):
        """Display videos in YouTube-style list"""
        # Clear existing content
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        if not videos:
            # Show no results message
            no_results = tk.Label(self.scrollable_frame,
                                  text="No videos found matching your criteria.",
                                  font=("Arial", 14), bg="#ecf0f1", fg="#7f8c8d")
            no_results.pack(pady=50)
            return

        # Display each video
        for video_data in videos:
            VideoItem(self.scrollable_frame, video_data, self.select_video, self.db)

        # Update video count
        self.video_count_label.config(text=f"Showing {len(videos)} of {len(self.all_videos)} videos")

    def select_video(self, video_path):
        """Handle video selection"""
        self.filename = video_path

        # Find the video data to get proper title
        video_title = "Selected Video"
        video_id = None
        for video in self.all_videos:
            if video['file_path'] == video_path:
                video_title = video.get('title', 'Selected Video')
                # Get video ID for uploaded lessons to increment views
                if video.get('type') == 'uploaded' and 'id' in video:
                    video_id = video['id']
                break

        self.selected_video_label.config(text=f"Now Playing: {video_title}")

        # Increment views for uploaded lessons
        if video_id:
            self.db.increment_views(video_id)
            # Refresh the video list to update view counts
            self.load_all_videos()

        self.open_video()

        # Switch to player tab
        tab_index = 1 if self.user_type == "student" else 2
        self.notebook.select(tab_index)

    # ---------------- Player Tab ---------------- #
    def setup_player_tab(self):
        # Configure style for player
        style = ttk.Style()
        style.configure("Player.TFrame", background="#2c3e50")
        self.player_frame.configure(style="Player.TFrame")

        # Create a fixed container for the video player
        self.player_container = tk.Frame(self.player_frame, bg="#2c3e50")
        self.player_container.pack(fill='both', expand=True, padx=10, pady=10)

        # Video display - fixed size container
        self.video_container = tk.Frame(self.player_container, bg="black", width=800, height=450)
        self.video_container.pack(pady=10)
        self.video_container.pack_propagate(False)  # Prevent container from resizing to content

        self.video_label = tk.Label(self.video_container, bg="black")
        self.video_label.pack(fill='both', expand=True)

        # Selected video info
        self.selected_video_label = tk.Label(self.player_container, text="No video selected",
                                             font=("Arial", 14, "bold"), bg="#2c3e50", fg="white")
        self.selected_video_label.pack(pady=5)

        # Controls frame - fixed at bottom
        self.controls_frame = tk.Frame(self.player_container, bg="#34495e", height=80)
        self.controls_frame.pack(fill='x', pady=5, side='bottom')
        self.controls_frame.pack_propagate(False)  # Fixed height

        # Control buttons
        btn_frame = tk.Frame(self.controls_frame, bg="#34495e")
        btn_frame.pack(pady=10)

        self.play_btn = tk.Button(btn_frame, text="▶ Play", command=self.play_video,
                                  bg="#3498db", fg="white", font=("Arial", 10, "bold"),
                                  relief="flat", width=8, cursor="hand2",
                                  activebackground="#2980b9")
        self.play_btn.pack(side='left', padx=5)

        self.pause_btn = tk.Button(btn_frame, text="⏸ Pause", command=self.pause_video,
                                   bg="#f39c12", fg="white", font=("Arial", 10, "bold"),
                                   relief="flat", width=8, cursor="hand2",
                                   activebackground="#e67e22")
        self.pause_btn.pack(side='left', padx=5)

        self.stop_btn = tk.Button(btn_frame, text="⏹ Stop", command=self.stop_video,
                                  bg="#e74c3c", fg="white", font=("Arial", 10, "bold"),
                                  relief="flat", width=8, cursor="hand2",
                                  activebackground="#c0392b")
        self.stop_btn.pack(side='left', padx=5)

        # Volume control
        volume_frame = tk.Frame(btn_frame, bg="#34495e")
        volume_frame.pack(side='left', padx=20)

        tk.Label(volume_frame, text="Volume:", fg="white", bg="#34495e",
                 font=("Arial", 9)).pack(side='left')

        self.volume_scale = tk.Scale(volume_frame, from_=0.0, to=5.0, resolution=0.1,
                                     orient="horizontal", variable=tk.DoubleVar(value=self.volume),
                                     command=self.set_volume, bg="#34495e", fg="white",
                                     highlightthickness=0, sliderrelief="flat",
                                     troughcolor="#7f8c8d", length=100)
        self.volume_scale.set(self.volume)
        self.volume_scale.pack(side='left', padx=5)

        # Seek bar
        seek_frame = tk.Frame(self.controls_frame, bg="#34495e")
        seek_frame.pack(fill='x', padx=10, pady=5)

        self.seek_var = tk.DoubleVar()
        self.seek_bar = tk.Scale(seek_frame, variable=self.seek_var, from_=0, to=100,
                                 orient="horizontal", length=800, command=self.seek_video,
                                 bg="#2c3e50", fg="white", highlightthickness=0,
                                 sliderrelief="flat", troughcolor="#7f8c8d")
        self.seek_bar.pack(fill='x', padx=10, pady=5)

        # Time label
        self.time_label = tk.Label(self.controls_frame, text="00:00 / 00:00 (Remaining: 00:00)",
                                   fg="white", bg="#34495e", font=("Arial", 10))
        self.time_label.pack(pady=5)

    def set_volume(self, value):
        self.volume = float(value)

    def open_video(self):
        if not self.filename:
            return
        self.cap = cv2.VideoCapture(self.filename)
        if not self.cap.isOpened():
            messagebox.showerror("Error", "Cannot open video file!")
            return
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.current_frame = 0
        self.seek_bar.config(to=self.total_frames)
        self.update_time_label()
        self.play_video()

    def play_video(self):
        if not self.cap:
            self.open_video()
        self.playing = True
        self.paused = False

        # Play audio if available
        audio_path = self.filename.replace(".avi", "_audio.wav")
        if os.path.exists(audio_path):
            threading.Thread(target=self.play_audio_file, args=(audio_path,), daemon=True).start()

        self.show_frame()

    def play_audio_file(self, audio_path):
        """Play audio with amplified volume"""
        try:
            data, fs = sf.read(audio_path, dtype='float32')
            data = np.clip(data * self.volume, -1.0, 1.0)  # Amplify safely
            sd.play(data, fs)
            sd.wait()
        except Exception as e:
            print(f"Error playing audio: {e}")

    def pause_video(self):
        self.paused = True
        sd.stop()

    def stop_video(self):
        self.playing = False
        sd.stop()
        if self.cap:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.current_frame = 0
            self.seek_var.set(0)
            self.update_time_label()
            self.video_label.config(image="")

    def seek_video(self, val):
        if self.cap:
            frame_num = int(float(val))
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            self.current_frame = frame_num
            self.update_time_label()

    def show_frame(self):
        if self.cap and self.playing and not self.paused:
            ret, frame = self.cap.read()
            if ret:
                self.current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Resize frame to fit the container while maintaining aspect ratio
                container_width = self.video_container.winfo_width()
                container_height = self.video_container.winfo_height()

                # If container dimensions are available, resize accordingly
                if container_width > 1 and container_height > 1:
                    h, w, _ = frame.shape
                    ratio = min(container_width / w, container_height / h)
                    new_w, new_h = int(w * ratio), int(h * ratio)
                    frame = cv2.resize(frame, (new_w, new_h))

                img = Image.fromarray(frame)
                imgtk = ImageTk.PhotoImage(image=img)
                self.video_label.imgtk = imgtk
                self.video_label.configure(image=imgtk)
                self.seek_var.set(self.current_frame)
                self.update_time_label()
                delay = int(1000 / self.fps)
                self.root.after(delay, self.show_frame)
            else:
                self.stop_video()

    def update_time_label(self):
        if self.cap:
            total_secs = int(self.total_frames / self.fps)
            current_secs = int(self.current_frame / self.fps)
            remaining_secs = total_secs - current_secs
            fmt = lambda t: f"{t // 60:02}:{t % 60:02}"
            self.time_label.config(text=f"{fmt(current_secs)} / {fmt(total_secs)} (Remaining: {fmt(remaining_secs)})")


if __name__ == "__main__":
    login_root = tk.Tk()
    login_app = LoginPage(login_root)
    login_root.mainloop()