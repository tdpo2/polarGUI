# Polar FTP GUI Documentation

## Overview

The Polar FTP GUI is a PyQt5 application that allows users to browse, download, and manage files on their Polar fitness device (Ignite, Vantage, etc.) via USB connection.


### GUI Installation

- Follow main code instructions for main installation
- Copy and replace files into main directory of main code
- To use GUI you need to install python and pyQt5 or PySide6 with command:
- pip install PyQt5
- pip install PySide6
- You are using GUI at your own risk

---

## GUI Capabilities

### Device Connection
- **List Devices**: Scan for available serial devices on Linux, macOS, or Windows
- **Connect**: Connect to a selected Polar device via USB
- **Device Info**: Automatically extracts device serial number for folder organization

### File Browser
- **Browse Directories**: Navigate the device's filesystem (e.g., `/U/0/`, `/U/1/`, etc.)
- **Directory Listing**: View files and folders with sizes
- **Navigation**: Navigate into subdirectories and up to parent directories
- **Sorting**: Sort by name, size, or date- C
- **Selection**: Check/uncheck files for download or deletion

### File Operations
- **Download**: Download selected files from device to local folder
- **Delete**: Delete selected files or directories from the device
- **Sync All**: Synchronize all data from device to local folder

### File Conversion (Bulk)
- **Input/Output Folders**: Select source and destination folders
- **Convert to TCX**: Convert Polar activity files to TCX format
- **Convert to GPX**: Convert Polar activity files to GPX format
- **Exercise List**: View all exercises with checkboxes for selective conversion

### Search
- **Search Exercises**: Filter exercises by name or path
- **Full Path Search**: Search includes subdirectory names (e.g., searching "2025" finds `2025-01-15/E/123456/activity.fit`)

### Sync Options
- **Use Polar/SERIAL Subfolder**: When enabled, creates `/Polar/<SERIAL>/` subfolder for synced files
- **Automatic Serial Detection**: Extracts device serial from USB connection

---

## Ruby File Changes for DELETE Option

To add DELETE functionality, the following Ruby files were modified:

### 1. `/polar/polar_ftp` (Main CLI Script)

**Changes Made**:
- Added DELETE command to the case statement
- Added usage message: `polar_ftp [options] DELETE <path>`
- Syntax fix: Ensured DELETE command was inside the case block

```ruby
when 'DELETE'
  # Delete file or directory
  remote_path = ARGV[1]
  unless remote_path
    usage
    exit -2
  end
  polar_ftp.delete(remote_path)
```

### 2. `/polar/lib/polar_ftp.rb` (Library Class)

**Changes Made**:
- Added new `delete(remote_path)` method that:
  - Sends REMOVE command (protobuf value 3) to Polar device
  - Constructs the proper protobuf message with command and path
  - Sends request to device via USB connection
  - Handles error cases (directory doesn't exist)
  - Returns boolean success status

```ruby
def delete(remote_path)
  puts "Deleting '#{remote_path}'"

  msg = PolarProtocol::PbPFtpOperation.encode(
    PolarProtocol::PbPFtpOperation.new(
      command: PolarProtocol::PbPFtpOperation::Command::REMOVE,
      path: remote_path))

  result = @polar_cnx.request(
    [ msg.length & 255, msg.length >> 8 ].pack("C*") + msg)

  # Check result for success/failure
  if result[0] == "\x00"
    puts "Error: Delete failed?"
    return false
  end

  puts "Successfully deleted '#{remote_path}'"
  true
end
```

---

## Usage Examples

### From Command Line

```bash
# List directory contents
./polar_ftp -d /dev/ttyUSB0 DIR /U/0/

# Download a file
./polar_ftp -d /dev/ttyUSB0 GET /U/0/20260101

# Delete a file or folder
./polar_ftp -d /dev/ttyUSB0 DELETE /U/0/20260101

# Sync all data
./polar_ftp -d /dev/ttyUSB0 SYNC ~/PolarData
```

### From GUI

1. **Connect**: Select device port and click "Connect"
2. **Browse**: Navigate to desired directory (e.g., `/U/0/`)
3. **Select**: Check files to download or delete
4. **Download/Delete**: Click "Download Selected" or "Delete Selected"
5. **Sync**: Click "Sync All" to synchronize all device data

---

## Notes

- The GUI automatically extracts the device serial number from the USB connection (printed to STDERR as `serial XXXXX`)
- Serial is used for creating organized output folders when "Use Polar/SERIAL subfolder" is enabled
- Search functionality now includes subdirectory names, not just filenames
- The DELETE operation permanently removes files from the device
