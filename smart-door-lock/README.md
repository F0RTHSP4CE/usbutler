# Smart Door Lock with EMV Authentication

A Python application that authenticates users via EMV payment cards using an ACR PC/SC USB NFC reader. When a valid EMV card is detected, the system extracts the PAN (Primary Account Number) and checks it against a user database to grant access.

## Features

- **EMV Card Reading**: Complete EMV protocol implementation for reading payment cards
- **PAN Extraction**: Extracts Primary Account Number from multiple EMV data sources
- **User Authentication**: JSON-based user database with PAN-based authentication  
- **Door Control**: Simulated smart door lock with auto-locking
- **PC/SC Support**: Works with ACR and other PC/SC compatible NFC readers

## Based on Unleashed Firmware EMV Implementation

This application is based on the comprehensive EMV parsing implementation from Unleashed Firmware, providing:

- Complete TLV (Tag-Length-Value) parsing engine
- Support for all major EMV tags and data structures
- Multi-source PAN extraction (direct PAN tag, Track 1/2 data)
- Robust error handling and data validation
- EMV command sequence implementation (SELECT PPSE, SELECT APP, GPO, READ RECORDS)

## Installation

1. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

2. **Connect your ACR PC/SC NFC reader** to USB port

3. **Verify reader detection:**
```bash
# On Linux, check if reader is detected
pcsc_scan
```

## Usage

### Running the Door Lock System

```bash
python smart_door_lock.py
```

The system will:
1. Display registered users
2. Wait for EMV cards to be placed on the reader
3. Extract PAN from the card
4. Authenticate against user database
5. Open door for valid users

### Adding New Users

```bash
python smart_door_lock.py --add-user
```

This will:
1. Read an EMV card to extract PAN
2. Prompt for user name and access level
3. Add the user to the database

### Testing EMV Functionality

```bash
# Test EMV parser with sample data
python test_emv.py --parser

# Test reading actual EMV cards
python test_emv.py --card
```

## File Structure

```
smart-door-lock/
├── smart_door_lock.py      # Main application
├── emv_parser.py           # EMV TLV parser (based on Unleashed Firmware)
├── nfc_reader.py           # PC/SC NFC reader interface
├── test_emv.py             # Testing utilities
├── users.json              # User database
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## EMV Implementation Details

### TLV Parser (`emv_parser.py`)

Based on the Unleashed Firmware implementation:

- **`parse_tag()`**: Parses EMV TLV tag and length encoding
- **`decode_tlv_tag()`**: Extracts data based on specific EMV tag types
- **`decode_response_tlv()`**: Recursive parser for nested TLV structures
- **`extract_pan_from_tlv()`**: Multi-method PAN extraction

### Supported EMV Tags

- **0x5A**: Primary Account Number (PAN)
- **0x5F20**: Cardholder Name
- **0x57**: Track 2 Equivalent Data
- **0x56**: Track 1 Equivalent Data
- **0x4F**: Application Identifier (AID)
- **0x50**: Application Label
- **0x9F12**: Application Name
- **And many more...**

### EMV Communication Flow

1. **SELECT PPSE** - Select Payment System Environment
2. **Extract AID** - Get Application Identifier from PPSE response
3. **SELECT Application** - Select specific payment application
4. **GET PROCESSING OPTIONS** - Retrieve processing parameters
5. **READ RECORDS** - Read application data from SFI records
6. **Extract PAN** - Parse TLV data to extract card number

### PAN Extraction Methods

The system tries multiple methods to extract PAN:

1. **Direct PAN Tag (0x5A)** - Most reliable method
2. **Track 2 Equivalent Data (0x57)** - Contains PAN + expiry
3. **Track 2 Data (0x9F6B)** - Alternative track format
4. **SFI Record Reading** - Scan application files for PAN data

## User Database

Simple JSON format:
```json
{
  "4111111111111111": {
    "name": "John Doe",
    "access_level": "admin",
    "active": true
  }
}
```

- **Key**: Card PAN (Primary Account Number)
- **name**: User's display name
- **access_level**: "user" or "admin"
- **active**: Enable/disable user access

## Security Considerations

⚠️ **Important Security Notes:**

1. **PAN Storage**: Card numbers are stored in plain text for simplicity. In production, use proper encryption/hashing
2. **Access Control**: Implement proper access logging and audit trails
3. **Card Security**: EMV cards contain sensitive financial data - ensure compliance with applicable regulations
4. **Physical Security**: Secure the NFC reader and system from tampering

## Hardware Requirements

- **NFC Reader**: ACR122U or other PC/SC compatible reader
- **Operating System**: Linux/Windows/macOS with PC/SC support
- **Python**: 3.7+
- **EMV Cards**: ISO14443-A compatible payment cards

## Troubleshooting

### Reader Not Detected
```bash
# Check if PC/SC daemon is running (Linux)
sudo systemctl status pcscd

# Start PC/SC daemon if needed
sudo systemctl start pcscd
```

### Card Reading Fails
- Ensure card is properly positioned on reader
- Try different cards (some cards may have restricted access)
- Check reader LED indicators
- Verify card is EMV-compatible (contactless payment card)

### PAN Not Found
- Some cards may have restricted data access
- Try different EMV applications on the card
- Check if card supports contactless transactions

## Development

### Adding New EMV Tags

To support additional EMV tags, modify `emv_parser.py`:

1. Add tag constant to `EMVTags` class
2. Add parsing logic in `decode_tlv_tag()` method
3. Add tag name mapping in `get_tag_name()` method

### Extending Authentication

The authentication system can be extended to support:
- Multiple card types (MIFARE, FeliCa, etc.)
- Biometric verification
- Time-based access control
- Remote management via network

## References

- **Unleashed Firmware EMV Implementation**: Complete reference implementation
- **EMV Specification**: Official EMV payment standards
- **ISO14443**: Contactless card communication standard
- **PC/SC Specification**: Smart card reader interface standard

## License

This project is for educational and research purposes. Ensure compliance with applicable laws and regulations when handling payment card data.
