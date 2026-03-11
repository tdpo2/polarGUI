#!/usr/bin/env python3
"""
Polar FTP GUI - Qt-based GUI for Polar device data management
Connects to Polar devices via USB, downloads data, and converts to TCX/GPX formats
"""

import os
import sys
import subprocess
import re
import shutil
import glob
from datetime import datetime

# Try to import PyQt5, fallback to PySide6 if not available
try:
    from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                  QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                  QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
                                  QListWidget, QListWidgetItem, QTextEdit, QFileDialog,
                                  QMessageBox, QSplitter,
                                  QComboBox, QGroupBox, QCheckBox, QStatusBar)
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
    from PyQt5.QtGui import QIcon, QFont
    QT_VERSION = 5
except ImportError:
    try:
        from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                        QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                        QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
                                        QListWidget, QListWidgetItem, QTextEdit, QFileDialog,
                                        QMessageBox, QSplitter,
                                        QComboBox, QGroupBox, QCheckBox, QStatusBar)
        from PySide6.QtCore import Qt, QThread, Signal as pyqtSignal, QTimer
        from PySide6.QtGui import QIcon, QFont
        QT_VERSION = 6
    except ImportError:
        print("Error: Neither PyQt5 nor PySide6 is installed.")
        print("Please install one of them:")
        print("  pip install PyQt5")
        print("  or")
        print("  pip install PySide6")
        sys.exit(1)


class WorkerThread(QThread):
    """Thread for running long-running operations"""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, func, *args):
        super().__init__()
        self.func = func
        self.args = args

    def run(self):
        try:
            result = self.func(*self.args)
            self.finished.emit(str(result) if result else "Done")
        except Exception as e:
            self.error.emit(str(e))


class PolarFTPGUI(QMainWindow):
    """Main GUI application for Polar FTP operations"""

    def __init__(self):
        super().__init__()

        # Configuration
        self.polar_dir = os.path.dirname(os.path.abspath(__file__))
        self.polar_ftp_script = os.path.join(self.polar_dir, "polar_ftp")
        self.polar_training2tcx = os.path.join(self.polar_dir, "polar_training2tcx")
        self.polar_training2gpx = os.path.join(self.polar_dir, "polar_training2gpx")

        # State
        self.device = ""
        self.device_serial = ""
        self.current_dir = "/U/0/"
        self.exercises = []

        # Setup UI
        self.init_ui()
        self.log("Polar FTP GUI initialized")
        self.log(f"Polar directory: {self.polar_dir}")

    def init_ui(self):
        """Initialize the UI"""
        self.setWindowTitle("Polar FTP GUI")
        self.setGeometry(100, 100, 1200, 800)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QVBoxLayout(central_widget)

        # Device connection section
        device_frame = self.create_device_section()
        main_layout.addWidget(device_frame)

        # Split view - Device browser and Conversion
        splitter = QSplitter(Qt.Horizontal)

        # Device browser
        browser_frame = self.create_browser_section()
        splitter.addWidget(browser_frame)

        # Conversion section
        conversion_frame = self.create_conversion_section()
        splitter.addWidget(conversion_frame)

        splitter.setSizes([500, 500])
        main_layout.addWidget(splitter)

        # Debug log
        debug_frame = self.create_debug_section()
        main_layout.addWidget(debug_frame)

        # Status bar
        self.statusBar().showMessage("Ready")

    def create_device_section(self):
        """Create device connection section"""
        group = QGroupBox("Device Connection")
        layout = QHBoxLayout()

        # Device selection
        layout.addWidget(QLabel("Device:"))
        self.device_input = QLineEdit()
        self.device_input.setPlaceholderText("/dev/ttyUSB0 or COM3")
        self.device_input.setText("/dev/ttyACM0")
        layout.addWidget(self.device_input)

        # Buttons
        self.list_devices_btn = QPushButton("List Devices")
        self.list_devices_btn.clicked.connect(self.list_devices)
        layout.addWidget(self.list_devices_btn)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_device)
        layout.addWidget(self.connect_btn)

        layout.addStretch()

        group.setLayout(layout)
        return group

    def create_browser_section(self):
        """Create device browser section"""
        group = QGroupBox("Device Browser")
        layout = QVBoxLayout()

        # Directory input
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Directory:"))
        self.dir_input = QLineEdit()
        self.dir_input.setText("/U/0/")
        dir_layout.addWidget(self.dir_input)

        self.go_btn = QPushButton("Go")
        self.go_btn.clicked.connect(self.change_directory)
        dir_layout.addWidget(self.go_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_directory)
        dir_layout.addWidget(self.refresh_btn)

        dir_layout.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Name", "Size", "Date"])
        self.sort_combo.currentTextChanged.connect(self.refresh_directory)
        dir_layout.addWidget(self.sort_combo)

        dir_layout.addWidget(QLabel("Order:"))
        self.sort_order_combo = QComboBox()
        self.sort_order_combo.addItems(["Ascending", "Descending"])
        self.sort_order_combo.currentTextChanged.connect(self.refresh_directory)
        dir_layout.addWidget(self.sort_order_combo)

        layout.addLayout(dir_layout)

        # File tree
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["✓", "Name", "Date", "Size", "Type"])
        self.file_tree.setColumnWidth(0, 50)
        self.file_tree.setColumnWidth(1, 180)
        self.file_tree.setColumnWidth(2, 100)
        self.file_tree.setColumnWidth(3, 80)
        self.file_tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.file_tree.installEventFilter(self)
        layout.addWidget(self.file_tree)

        # Action buttons
        btn_layout = QHBoxLayout()
        self.download_btn = QPushButton("Download Selected")
        self.download_btn.clicked.connect(self.download_selected)
        btn_layout.addWidget(self.download_btn)

        self.sync_btn = QPushButton("Sync All")
        self.sync_btn.clicked.connect(self.sync_all)
        btn_layout.addWidget(self.sync_btn)

        self.sync_use_serial_subfolder = QCheckBox("Use /Polar/Serial subfolder")
        self.sync_use_serial_subfolder.setChecked(True)
        btn_layout.addWidget(self.sync_use_serial_subfolder)

        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self.delete_selected)
        btn_layout.addWidget(self.delete_btn)

        layout.addLayout(btn_layout)

        group.setLayout(layout)
        return group

    def create_conversion_section(self):
        """Create conversion section"""
        group = QGroupBox("File Conversion(Bulk)")
        layout = QVBoxLayout()

        # Input folder
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("Input Folder:"))
        self.input_folder = QLineEdit()
        input_layout.addWidget(self.input_folder)

        self.browse_input_btn = QPushButton("Browse")
        self.browse_input_btn.clicked.connect(self.browse_input)
        input_layout.addWidget(self.browse_input_btn)



        layout.addLayout(input_layout)

        # Output folder
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output Folder:"))
        self.output_folder = QLineEdit()
        output_layout.addWidget(self.output_folder)

        self.browse_output_btn = QPushButton("Browse")
        self.browse_output_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(self.browse_output_btn)

        layout.addLayout(output_layout)

        # Only convert checked exercises (moved below Output folder)
        self.only_checked_checkbox = QCheckBox("Only convert checked exercises")
        layout.addWidget(self.only_checked_checkbox)

        # Convert buttons
        convert_layout = QHBoxLayout()
        self.convert_tcx_btn = QPushButton("Convert to TCX")
        self.convert_tcx_btn.clicked.connect(self.convert_to_tcx)
        convert_layout.addWidget(self.convert_tcx_btn)

        self.convert_gpx_btn = QPushButton("Convert to GPX")
        self.convert_gpx_btn.clicked.connect(self.convert_to_gpx)
        convert_layout.addWidget(self.convert_gpx_btn)

        layout.addLayout(convert_layout)

        # Remove duplicate checkbox if it exists elsewhere
        # (This section cleaned up - checkbox moved above)

        # Exercises list with checkboxes
        layout.addWidget(QLabel("Exercises:"))
        self.exercises_list = QTreeWidget()
        self.exercises_list.setHeaderLabels(["✓", "Exercise"])
        self.exercises_list.setColumnWidth(0, 40)

        layout.addWidget(self.exercises_list)

        # Search
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self.search_activities)
        search_layout.addWidget(self.search_input)

        layout.addLayout(search_layout)

        group.setLayout(layout)
        return group

    def create_debug_section(self):
        """Create debug log section"""
        group = QGroupBox("Debug Log")
        layout = QVBoxLayout()

        self.debug_text = QTextEdit()
        self.debug_text.setReadOnly(True)
        self.debug_text.setFont(QFont("Courier", 9))
        layout.addWidget(self.debug_text)

        # Buttons
        btn_layout = QHBoxLayout()
        self.copy_debug_btn = QPushButton("Copy All")
        self.copy_debug_btn.clicked.connect(self.copy_debug)
        btn_layout.addWidget(self.copy_debug_btn)

        self.clear_debug_btn = QPushButton("Clear")
        self.clear_debug_btn.clicked.connect(self.clear_debug)
        btn_layout.addWidget(self.clear_debug_btn)

        btn_layout.addStretch()

        layout.addLayout(btn_layout)

        group.setLayout(layout)
        return group

    def eventFilter(self, obj, event):
        """Handle key press events for navigation"""
        if obj == self.file_tree and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Up:
                self.navigate_up_directory()
                return True
        return super().eventFilter(obj, event)

    def navigate_up_directory(self):
        """Navigate to parent directory"""
        if self.current_dir and self.current_dir != "/":
            # Get parent directory
            parent_dir = os.path.dirname(self.current_dir.rstrip('/'))
            if not parent_dir:
                parent_dir = "/"
            self.current_dir = parent_dir
            self.dir_input.setText(self.current_dir)
            self.change_directory()
            self.log(f"Navigated to: {self.current_dir}")

    def log(self, message, level="INFO"):
        """Add timestamped message to debug log"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] [{level}] {message}\n"

        self.debug_text.append(log_entry)
        self.debug_text.verticalScrollBar().setValue(
            self.debug_text.verticalScrollBar().maximum()
        )

    def run_command(self, cmd, capture_output=True, check=True):
        """Run a command and return result"""
        self.log(f"Running: {' '.join(cmd)}")

        try:
            if capture_output:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=check,
                    cwd=self.polar_dir
                )
                if result.stdout:
                    self.log(result.stdout.strip())
                if result.stderr:
                    self.log(result.stderr.strip(), "WARNING")
                return result
            else:
                subprocess.run(cmd, check=True, cwd=self.polar_dir)
                return None

        except subprocess.CalledProcessError as e:
            self.log(f"Command failed: {e}", "ERROR")
            if e.stdout:
                self.log(f"stdout: {e.stdout}", "ERROR")
            if e.stderr:
                self.log(f"stderr: {e.stderr}", "ERROR")
            raise
        except FileNotFoundError:
            self.log(f"Command not found: {cmd[0]}", "ERROR")
            raise

    def list_devices(self):
        """List available serial devices"""
        self.log("Scanning for devices...")

        if sys.platform.startswith('linux'):
            devices = []
            for pattern in ['/dev/ttyUSB*', '/dev/ttyACM*', '/dev/tty.*']:
                devices.extend(glob.glob(pattern))
            devices = sorted(set(devices))

        elif sys.platform == 'darwin':
            devices = []
            for pattern in ['/dev/tty.*', '/dev/cu.*']:
                devices.extend(glob.glob(pattern))
            devices = sorted(set([d for d in devices if 'Bluetooth' not in d]))

        else:
            try:
                import serial.tools.list_ports
                devices = [p.device for p in serial.tools.list_ports.comports()]
            except:
                devices = [f"COM{i}" for i in range(1, 10)]

        if devices:
            self.log(f"Found devices: {', '.join(devices)}")
            # Auto-fill device field
            if devices:
                self.device_input.setText(devices[0])
                self.log(f"Auto-filled device: {devices[0]}")
            QMessageBox.information(self, "Devices Found", "\n".join(devices))
        else:
            self.log("No devices found", "WARNING")
            QMessageBox.warning(self, "No Devices", "No serial devices found")

    def connect_device(self):
        """Connect to device"""
        self.device = self.device_input.text().strip()
        if not self.device:
            QMessageBox.warning(self, "Error", "Please specify a device")
            return

        self.log(f"Connecting to device: {self.device}")

        try:
            self.change_directory()
            self.log("Device connected successfully")
            QMessageBox.information(self, "Connected", f"Connected to {self.device}")
        except Exception as e:
            self.log(f"Connection failed: {e}", "ERROR")
            QMessageBox.critical(self, "Connection Failed", str(e))

    def change_directory(self):
        """Change to specified directory"""
        self.current_dir = self.dir_input.text().strip()
        if not self.current_dir:
            self.current_dir = "/"

        cmd = [self.polar_ftp_script]
        if self.device:
            cmd.extend(["-d", self.device])
        cmd.extend(["DIR", self.current_dir])

        self.log(f"Listing directory: {self.current_dir}")

        try:
            result = self.run_command(cmd)
            # Extract serial number from output if not already set
            # Serial goes to STDERR with format: "Connected to PRODUCT serial XXXXXX"
            if not self.device_serial:
                output = (result.stdout or '') + '\n' + (result.stderr or '')
                for line in output.split('\n'):
                    if 'serial' in line.lower():
                        # Format: "Connected to PRODUCT serial XXXXXX"
                        # Extract the last word as serial number
                        words = line.strip().split()
                        if len(words) >= 2:
                            self.device_serial = words[-1]
                            self.log(f"Device serial: {self.device_serial}")
                            break
            self.parse_directory_listing(result.stdout)
            # Force GUI update
            QApplication.processEvents()
        except Exception as e:
            self.log(f"Failed to list directory: {e}", "ERROR")

    def refresh_directory(self):
        """Refresh current directory"""
        self.change_directory()

    def on_item_double_clicked(self, item, column):
        """Handle double-click on file tree to navigate into folders"""
        name = item.text(0)

        # Check if it's a directory (ends with /)
        if name.endswith('/'):
            # Navigate into the folder
            current = self.current_dir.strip()
            if not current:
                current = "/"

            # Build new path
            if current.endswith('/'):
                new_path = current + name.rstrip('/')
            else:
                new_path = current + '/' + name.rstrip('/')

            self.current_dir = new_path
            self.dir_input.setText(new_path)
            self.change_directory()

    def parse_directory_listing(self, output):
        """Parse directory listing from polar_ftp"""
        # Clear current list
        self.file_tree.clear()

        self.exercises = []
        items_list = []

        lines = output.strip().split('\n')

        for line in lines:
            if not line or not line.strip():
                continue

            # Parse: "   filename              12345" or "   subdir/"
            if line.startswith('   '):
                name = line.lstrip()

                # Check if it's a directory
                is_dir = name.endswith('/')

                if is_dir:
                    name = name.rstrip('/')
                    # Try to extract date from directory name (format: YYYY-MM-DD or similar)
                    date_str = ''
                    if len(name) >= 10 and name[4] == '-' and name[7] == '-':
                        date_str = name[:10]
                    item = QTreeWidgetItem(['', name + '/', date_str, '', 'Directory'])
                    item_data = {'item': item, 'name': name, 'size': 0, 'is_dir': True, 'date': date_str}
                else:
                    # Try to parse size
                    parts = name.split()
                    if len(parts) >= 2:
                        filename = ' '.join(parts[:-1])
                        size = parts[-1]
                        try:
                            size = int(size)
                            size_str = self.format_size(size)
                        except:
                            size_str = parts[-1]
                            size = 0
                        item = QTreeWidgetItem(['', filename, '', size_str, 'File'])
                        item_data = {'item': item, 'name': filename, 'size': size, 'is_dir': False, 'date': ''}

                    # Track activity files
                    if any(filename.lower().endswith(ext) for ext in ['.fit', '.pfs', '.srd']):
                        self.exercises.append(self.current_dir + filename)

                # Make item checkable
                item.setCheckState(0, Qt.Unchecked)
                items_list.append(item_data)

        # Sort items based on selected sort option
        sort_option = self.sort_combo.currentText()
        sort_order = self.sort_order_combo.currentText()
        reverse_order = (sort_order == "Descending")

        if sort_option == "Name":
            # Sort by name (directories first, then alphabetically)
            items_list.sort(key=lambda x: (not x['is_dir'], x['name'].lower()), reverse=reverse_order)
        elif sort_option == "Size":
            # Sort by size (directories first, then by size)
            items_list.sort(key=lambda x: (not x['is_dir'], x['size']), reverse=reverse_order)
        elif sort_option == "Date":
            # Sort by date (directories first, then by date)
            items_list.sort(key=lambda x: (not x['is_dir'], x['date'], x['name'].lower()), reverse=reverse_order)

        # Add sorted items to tree
        for item_data in items_list:
            self.file_tree.addTopLevelItem(item_data['item'])

        # Force GUI update
        QApplication.processEvents()

    def format_size(self, size):
        """Format file size"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def download_selected(self):
        """Download selected files"""
        selected_items = self.file_tree.selectedItems()
        checked_items = self.get_checked_items()

        # Combine unique items
        all_items = selected_items + [item for item in checked_items if item not in selected_items]

        if not all_items:
            QMessageBox.information(self, "Info", "Please select or check files to download")
            return

        # Ask for output directory
        output_dir = QFileDialog.getExistingDirectory(self, "Select output directory")
        if not output_dir:
            return

        for item in all_items:
            name = item.text(1)  # Name is now in column 1
            if name.endswith('/'):
                continue

            self.log(f"Downloading: {name}")

            cmd = [self.polar_ftp_script]
            if self.device:
                cmd.extend(["-d", self.device])
            cmd.extend(["GET", os.path.join(self.current_dir, name), output_dir])

            try:
                self.run_command(cmd)
                self.log(f"Downloaded: {name}")
            except Exception as e:
                self.log(f"Failed to download {name}: {e}", "ERROR")

        self.log("Download complete")

    def sync_all(self):
        """Sync all files from device"""
        # Check if device is set
        if not self.device:
            QMessageBox.warning(self, "Not Connected", "Please connect to a device first")
            return

        # If serial not extracted yet, extract it now
        if not self.device_serial:
            self.log("Extracting device serial...")
            try:
                # Run a simple command to get the serial number
                cmd = [self.polar_ftp_script]
                cmd.extend(["-d", self.device])
                cmd.extend(["DIR", "/"])
                result = self.run_command(cmd)
                # Serial extraction happens in change_directory, but we can also check output here
                output = (result.stdout or '') + '\n' + (result.stderr or '')
                for line in output.split('\n'):
                    if 'serial' in line.lower():
                        words = line.strip().split()
                        if len(words) >= 2:
                            self.device_serial = words[-1]
                            self.log(f"Device serial: {self.device_serial}")
                            break
            except Exception as e:
                self.log(f"Could not extract serial: {e}", "WARNING")

        # Ask user to select base output directory
        base_output_dir = "/Polar"
        output_dir = QFileDialog.getExistingDirectory(self, "Select sync output directory", base_output_dir)
        if not output_dir:
            return

        # Add Polar/Serial subfolder if checkbox is checked and serial is available
        self.log(f"Debug: device_serial='{self.device_serial}', checkbox_exists={hasattr(self, 'sync_use_serial_subfolder')}")
        if hasattr(self, 'sync_use_serial_subfolder'):
            self.log(f"Debug: checkbox_checked={self.sync_use_serial_subfolder.isChecked()}")

        if self.device_serial and hasattr(self, 'sync_use_serial_subfolder') and self.sync_use_serial_subfolder.isChecked():
            output_dir = os.path.join(output_dir, "Polar", self.device_serial)
            self.log(f"Debug: Using serial subfolder: {output_dir}")
        else:
            self.log(f"Debug: NOT using serial subfolder, output_dir={output_dir}")

        cmd = [self.polar_ftp_script]
        if self.device:
            cmd.extend(["-d", self.device])
        cmd.extend(["SYNC", output_dir])

        self.log("Starting sync...")

        try:
            # Use subprocess.Popen to read output in real-time
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.polar_dir)

            # Read stdout line by line and log to debug window
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    self.log(line.strip())
                    # Force GUI update
                    QApplication.processEvents()

            # Also read any remaining stderr
            stderr = process.stderr.read()
            if stderr:
                self.log(stderr.strip(), "WARNING")

            self.log("Sync complete")
        except Exception as e:
            self.log(f"Sync failed: {e}", "ERROR")

    def get_checked_items(self):
        """Get all checked items from the file tree"""
        checked_items = []
        iterator = QTreeWidgetItemIterator(self.file_tree)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.Checked:
                checked_items.append(item)
            iterator += 1
        return checked_items

    def get_checked_exercises(self):
        """Get all checked items from the exercises list"""
        checked_items = []
        iterator = QTreeWidgetItemIterator(self.exercises_list)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == Qt.Checked:
                checked_items.append(item)
            iterator += 1
        return checked_items

    def delete_selected(self):
        """Delete checked files/directories from device"""
        # Get only checked items (with checkmarks)
        checked_items = self.get_checked_items()

        if not checked_items:
            QMessageBox.information(self, "Info", "Please check files/directories to delete")
            return

        # Confirm deletion
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Are you sure you want to delete {len(checked_items)} checked item(s)?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        for item in checked_items:
            name = item.text(1)  # Name is now in column 1
            # Remove trailing slash for directory if present
            if name.endswith('/'):
                name = name.rstrip('/')

            self.log(f"Deleting: {name}")

            cmd = [self.polar_ftp_script]
            if self.device:
                cmd.extend(["-d", self.device])
            cmd.extend(["DELETE", os.path.join(self.current_dir, name)])

            try:
                self.run_command(cmd)
                self.log(f"Deleted: {name}")
                # Remove item from tree
                parent = item.parent()
                if parent:
                    parent.removeChild(item)
                else:
                    # It's a root item
                    index = self.file_tree.indexOfTopLevelItem(item)
                    if index >= 0:
                        self.file_tree.takeTopLevelItem(index)
            except Exception as e:
                self.log(f"Failed to delete {name}: {e}", "ERROR")

        self.log("Delete complete")

    def browse_input(self):
        """Browse for input folder"""
        folder = QFileDialog.getExistingDirectory(self, "Select input folder")
        if folder:
            self.input_folder.setText(folder)
            self.scan_activities(folder)

    def browse_output(self):
        """Browse for output folder"""
        folder = QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self.output_folder.setText(folder)

    def scan_activities(self, folder):
        """Scan folder for exercise files"""
        self.exercises_list.clear()
        self.exercises = []

        if not os.path.isdir(folder):
            return

        # Method 1: Look for .fit, .pfs, .srd files directly
        for root, dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(('.fit', '.pfs', '.srd')):
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, folder)
                    self.exercises.append(full_path)
                    item = QTreeWidgetItem(['', rel_path])
                    item.setCheckState(0, Qt.Unchecked)
                    item.setData(1, 0, full_path)  # Store full path in column 1 data
                    self.exercises_list.addTopLevelItem(item)

        # Method 2: Look for synced folder structure: YYYYMMDD/E/HHMMSS/
        for root, dirs, files in os.walk(folder):
            if 'E' in dirs:
                e_path = os.path.join(root, 'E')
                if os.path.isdir(e_path):
                    for time_folder in os.listdir(e_path):
                        time_path = os.path.join(e_path, time_folder)
                        if os.path.isdir(time_path) and len(time_folder) == 6 and time_folder.isdigit():
                            for f in os.listdir(time_path):
                                if f.upper() in ('PHYSDATA.BPB', 'TSESS.BPB', 'SAMPLE.BPB'):
                                    if time_path not in self.exercises:
                                        self.exercises.append(time_path)
                                        rel_path = os.path.relpath(time_path, folder)
                                        item = QTreeWidgetItem(['', rel_path])
                                        item.setCheckState(0, Qt.Unchecked)
                                        item.setData(1, 0, time_path)  # Store full path in column 1 data
                                        self.exercises_list.addTopLevelItem(item)
                                    break

        self.log(f"Found {len(self.exercises)} exercise files in {folder}")

    def search_activities(self):
        """Search activities by name"""
        query = self.search_input.text().strip().lower()

        # Re-scan to get all activities
        folder = self.input_folder.text().strip()
        if not folder:
            return

        self.exercises_list.clear()

        if not query:
            for a in self.exercises:
                item = QTreeWidgetItem(['', os.path.relpath(a, folder)])
                item.setCheckState(0, Qt.Unchecked)
                item.setData(1, 0, a)  # Store full path in column 1 data
                self.exercises_list.addTopLevelItem(item)
            return

        for a in self.exercises:
            rel_path = os.path.relpath(a, folder)
            if query in rel_path.lower():
                item = QTreeWidgetItem(['', rel_path])
                item.setCheckState(0, Qt.Unchecked)
                item.setData(1, 0, a)  # Store full path in column 1 data
                self.exercises_list.addTopLevelItem(item)

    def convert_to_tcx(self):
        """Convert activity files to TCX format"""
        input_folder = self.input_folder.text().strip()
        output_folder = self.output_folder.text().strip()

        if not input_folder or not os.path.isdir(input_folder):
            QMessageBox.warning(self, "Error", "Please select a valid input folder")
            return

        if not output_folder:
            QMessageBox.warning(self, "Error", "Please select an output folder")
            return

        # Find all activity directories
        activity_dirs = []

        # Check if we should only convert checked exercises
        if self.only_checked_checkbox.isChecked():
            checked_items = self.get_checked_exercises()
            if not checked_items:
                QMessageBox.information(self, "Info", "No exercises checked. Please check exercises to convert.")
                return
            for item in checked_items:
                full_path = item.data(1, 0)
                if full_path:
                    activity_dirs.append(full_path)
        else:
            # Method 1: Look for .fit, .pfs, .srd files
            for root, dirs, files in os.walk(input_folder):
                for f in files:
                    if f.lower().endswith(('.fit', '.pfs', '.srd')):
                        if root not in activity_dirs:
                            activity_dirs.append(root)

            # Method 2: Look for synced folder structure
            for root, dirs, files in os.walk(input_folder):
                if 'E' in dirs:
                    e_path = os.path.join(root, 'E')
                    if os.path.isdir(e_path):
                        for time_folder in os.listdir(e_path):
                            time_path = os.path.join(e_path, time_folder)
                            if os.path.isdir(time_path) and len(time_folder) == 6 and time_folder.isdigit():
                                for f in os.listdir(time_path):
                                    if f.upper() in ('PHYSDATA.BPB', 'TSESS.BPB', 'SAMPLE.BPB'):
                                        if time_path not in activity_dirs:
                                            activity_dirs.append(time_path)
                                        break

        if not activity_dirs:
            QMessageBox.information(self, "Info", "No activity files found in input folder")
            return

        self.log(f"Converting {len(activity_dirs)} activities to TCX...")

        converted = 0
        for activity_dir in activity_dirs:
            try:
                self.log(f"Processing: {activity_dir}")

                date_str = self.extract_date(activity_dir)

                if date_str:
                    output_file = os.path.join(output_folder, f"{date_str}.tcx")
                else:
                    output_file = os.path.join(output_folder, "output.tcx")

                # Handle duplicate filenames
                base_output = output_file
                counter = 1
                while os.path.exists(output_file):
                    name, ext = os.path.splitext(base_output)
                    output_file = f"{name}_{counter}{ext}"
                    counter += 1

                cmd = [self.polar_training2tcx, activity_dir, output_file]
                self.run_command(cmd, check=False)

                if os.path.exists(output_file):
                    converted += 1
                    self.log(f"Created: {os.path.basename(output_file)}")

                # Force GUI update
                QApplication.processEvents()

            except Exception as e:
                self.log(f"Failed to convert {activity_dir}: {e}", "ERROR")

        self.log(f"Conversion complete: {converted} files created")
        QMessageBox.information(self, "Complete", f"Converted {converted} files to TCX")

    def convert_to_gpx(self):
        """Convert activity files to GPX format"""
        input_folder = self.input_folder.text().strip()
        output_folder = self.output_folder.text().strip()

        if not input_folder or not os.path.isdir(input_folder):
            QMessageBox.warning(self, "Error", "Please select a valid input folder")
            return

        if not output_folder:
            QMessageBox.warning(self, "Error", "Please select an output folder")
            return

        activity_dirs = []

        # Check if we should only convert checked exercises
        if self.only_checked_checkbox.isChecked():
            checked_items = self.get_checked_exercises()
            if not checked_items:
                QMessageBox.information(self, "Info", "No exercises checked. Please check exercises to convert.")
                return
            for item in checked_items:
                full_path = item.data(1, 0)
                if full_path:
                    activity_dirs.append(full_path)
        else:
            # Method 1: Look for .fit, .pfs, .srd files
            for root, dirs, files in os.walk(input_folder):
                for f in files:
                    if f.lower().endswith(('.fit', '.pfs', '.srd')):
                        if root not in activity_dirs:
                            activity_dirs.append(root)

            # Method 2: Look for synced folder structure
            for root, dirs, files in os.walk(input_folder):
                if 'E' in dirs:
                    e_path = os.path.join(root, 'E')
                    if os.path.isdir(e_path):
                        for time_folder in os.listdir(e_path):
                            time_path = os.path.join(e_path, time_folder)
                            if os.path.isdir(time_path) and len(time_folder) == 6 and time_folder.isdigit():
                                for f in os.listdir(time_path):
                                    if f.upper() in ('PHYSDATA.BPB', 'TSESS.BPB', 'SAMPLE.BPB'):
                                        if time_path not in activity_dirs:
                                            activity_dirs.append(time_path)
                                        break

        if not activity_dirs:
            QMessageBox.information(self, "Info", "No activity files found")
            return

        self.log(f"Converting {len(activity_dirs)} activities to GPX...")

        converted = 0
        for activity_dir in activity_dirs:
            try:
                self.log(f"Processing: {activity_dir}")

                date_str = self.extract_date(activity_dir)

                if date_str:
                    output_file = os.path.join(output_folder, f"{date_str}.gpx")
                else:
                    output_file = os.path.join(output_folder, "output.gpx")

                base_output = output_file
                counter = 1
                while os.path.exists(output_file):
                    name, ext = os.path.splitext(base_output)
                    output_file = f"{name}_{counter}{ext}"
                    counter += 1

                cmd = [self.polar_training2gpx, activity_dir, output_file]
                self.run_command(cmd, check=False)

                if os.path.exists(output_file):
                    converted += 1
                    self.log(f"Created: {os.path.basename(output_file)}")

                QApplication.processEvents()

            except Exception as e:
                self.log(f"Failed to convert {activity_dir}: {e}", "ERROR")

        self.log(f"Conversion complete: {converted} files created")
        QMessageBox.information(self, "Complete", f"Converted {converted} files to GPX")

    def extract_date(self, path):
        """Extract date from path for filename"""
        # Look for YYYYMMDD and HHMMSS in path
        date_matches = re.findall(r'\d{8}', path)
        time_matches = re.findall(r'\d{6}', path)

        if date_matches and time_matches:
            return f"{date_matches[0]}-{time_matches[0]}"

        # Try other patterns
        basename = os.path.basename(path)
        patterns = [
            (r'(\d{8})-(\d{6})', '%Y%m%d-%H%M%S'),
            (r'(\d{4})_(\d{2})_(\d{2})', '%Y_%m_%d'),
            (r'(\d{8})', '%Y%m%d'),
        ]

        for pattern, fmt in patterns:
            match = re.search(pattern, basename)
            if match:
                try:
                    date_str = ''.join(match.groups())
                    dt = datetime.strptime(date_str, fmt)
                    return dt.strftime('%Y%m%d-%H%M%S')
                except:
                    pass

        return datetime.now().strftime('%Y%m%d-%H%M%S')



    def scan_device_exercises(self):
        """Scan device /U/0/ for exercises"""
        if not self.device:
            QMessageBox.warning(self, "Error", "Please connect to a device first")
            return

        output_folder = self.output_folder.text().strip()
        if not output_folder:
            QMessageBox.warning(self, "Error", "Please select an output folder")
            return

        self.log("Scanning device for exercises at /U/0/...")

        remote_base = "/U/0/"
        cmd = [self.polar_ftp_script, "-d", self.device, "DIR", remote_base]

        try:
            result = self.run_command(cmd)
            # Debug: Show raw directory listing
            self.log(f"Raw DIR output for /U/0/:")
            self.log(result.stdout)
            date_folders = self.parse_date_folders(result.stdout)

            if not date_folders:
                self.log("No date folders found in /U/0/", "WARNING")
                QMessageBox.information(self, "Info", "No date folders found in /U/0/")
                return

            self.log(f"Found {len(date_folders)} date folders")

            exercise_count = 0
            converted_count = 0

            for date_folder in date_folders:
                date_path = os.path.join(remote_base, date_folder)
                cmd = [self.polar_ftp_script, "-d", self.device, "DIR", date_path]
                result = self.run_command(cmd)

                e_folders = self.parse_e_folders(result.stdout)

                for e_folder in e_folders:
                    e_path = os.path.join(date_path, e_folder)
                    cmd = [self.polar_ftp_script, "-d", self.device, "DIR", e_path]
                    result = self.run_command(cmd)

                    time_folders = self.parse_time_folders(result.stdout)

                    for time_folder in time_folders:
                        exercise_count += 1
                        self.log(f"Found exercise: {date_folder}/{e_folder}/{time_folder}")

                        import tempfile
                        temp_dir = tempfile.mkdtemp(prefix="polar_")

                        exercise_path = os.path.join(e_path, time_folder)
                        cmd = [self.polar_ftp_script, "-d", self.device, "GET", exercise_path, temp_dir]

                        try:
                            self.run_command(cmd, check=False)

                            exercise_files = []
                            for root, dirs, files in os.walk(temp_dir):
                                for f in files:
                                    if f.lower().endswith(('.fit', '.pfs', '.srd', '.BPB')):
                                        exercise_files.append(os.path.join(root, f))

                            if exercise_files:
                                exercise_dir = os.path.dirname(exercise_files[0])
                                output_filename = f"{date_folder}-{time_folder}.tcx"
                                output_path = os.path.join(output_folder, output_filename)

                                base_output = output_path
                                counter = 1
                                while os.path.exists(output_path):
                                    name, ext = os.path.splitext(base_output)
                                    output_path = f"{name}_{counter}{ext}"
                                    counter += 1

                                cmd = [self.polar_training2tcx, exercise_dir, output_path]
                                self.run_command(cmd, check=False)

                                if os.path.exists(output_path):
                                    converted_count += 1
                                    self.log(f"Converted: {os.path.basename(output_path)}")

                        except Exception as e:
                            self.log(f"Failed to process exercise: {e}", "ERROR")
                        finally:
                            try:
                                shutil.rmtree(temp_dir)
                            except:
                                pass

                        QApplication.processEvents()

            self.log(f"Scan complete: found {exercise_count} exercises, converted {converted_count}")
            QMessageBox.information(self, "Complete", f"Found {exercise_count} exercises, converted {converted_count} to TCX")

        except Exception as e:
            self.log(f"Failed to scan device: {e}", "ERROR")
            QMessageBox.critical(self, "Error", f"Failed to scan device: {e}")

    def parse_date_folders(self, output):
        """Parse date folders from directory listing"""
        folders = []
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('   '):
                name = line.lstrip().rstrip('/')
                # Handle 8-digit format (YYYYMMDD)
                if name.isdigit() and len(name) == 8:
                    folders.append(name)
                # Handle YYYY-MM-DD format
                elif len(name) == 10 and name[4] == '-' and name[7] == '-':
                    folders.append(name)
        return folders

    def parse_e_folders(self, output):
        """Parse E (exercise) folders from directory listing"""
        folders = []
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('   '):
                name = line.lstrip().rstrip('/')
                if name.upper() == 'E':
                    folders.append(name)
        return folders

    def parse_time_folders(self, output):
        """Parse time folders from directory listing"""
        folders = []
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('   '):
                name = line.lstrip().rstrip('/')
                if name.isdigit() and len(name) == 6:
                    folders.append(name)
        return folders

    def copy_debug(self):
        """Copy debug log to clipboard"""
        text = self.debug_text.toPlainText()
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.log("Debug log copied to clipboard")

    def clear_debug(self):
        """Clear debug log"""
        self.debug_text.clear()
        self.log("Debug log cleared")


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    window = PolarFTPGUI()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
