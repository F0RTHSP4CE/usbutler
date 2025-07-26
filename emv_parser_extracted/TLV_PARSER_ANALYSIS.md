# EMV TLV Parser Analysis

## Overview

The EMV TLV (Tag-Length-Value) parser is the core component responsible for extracting structured data from EMV payment cards. This analysis details the implementation found in `emv_poller_i.c`.

## TLV Structure

EMV uses BER-TLV (Basic Encoding Rules) format:
- **Tag**: 1-2 bytes identifying the data type
- **Length**: 1-2 bytes indicating data length
- **Value**: Variable length data

## Key Parsing Functions

### 1. `emv_parse_tag()`

Parses TLV tag and length information:

```c
static bool emv_parse_tag(const uint8_t* buff, uint16_t len, uint16_t* t, uint8_t* tl, uint8_t* off)
```

**Features:**
- Handles both 1-byte and 2-byte tags
- Supports short (1-byte) and long (2-byte) length encoding
- Returns parsed tag, length, and buffer offset

**Tag Detection:**
- If `(first_byte & 31) == 31`: 2-byte tag
- Otherwise: 1-byte tag

**Length Detection:**
- If `(tlen & 128) == 128`: Long form length (next byte contains actual length)
- Otherwise: Short form length

### 2. `emv_decode_tlv_tag()`

Extracts specific data based on EMV tag type:

```c
static bool emv_decode_tlv_tag(const uint8_t* buff, uint16_t tag, uint8_t tlen, EmvApplication* app)
```

**Supported Tags:**

#### Card Information
- **EMV_TAG_PAN (0x5A)**: Primary Account Number
- **EMV_TAG_CARDHOLDER_NAME (0x5F20)**: Cardholder name with space termination
- **EMV_TAG_EXP_DATE (0x5F24)**: Card expiration date

#### Track Data
- **EMV_TAG_TRACK_1_EQUIV (0x56)**: Track 1 equivalent data
- **EMV_TAG_TRACK_2_EQUIV (0x57)**: Track 2 equivalent data with PAN/expiry parsing
- **EMV_TAG_TRACK_2_DATA (0x9F6B)**: Alternative track 2 format

#### Application Data
- **EMV_TAG_AID (0x4F)**: Application Identifier
- **EMV_TAG_APPL_LABEL (0x50)**: Application label
- **EMV_TAG_APPL_NAME (0x9F12)**: Application name
- **EMV_TAG_APPL_INTERCHANGE_PROFILE (0x82)**: Application interchange profile

#### Transaction Data
- **EMV_TAG_LOG_ENTRY (0x9F4D)**: Transaction log entry information
- **EMV_TAG_LOG_FMT (0x9F4F)**: Transaction log format template
- **EMV_TAG_ATC (0x9F36)**: Application Transaction Counter
- **EMV_TAG_LOG_AMOUNT (0x9F02)**: Transaction amount
- **EMV_TAG_LOG_DATE (0x9A)**: Transaction date
- **EMV_TAG_LOG_TIME (0x9F21)**: Transaction time
- **EMV_TAG_LOG_COUNTRY (0x9F1A)**: Transaction country
- **EMV_TAG_LOG_CURRENCY (0x5F2A)**: Transaction currency

#### Security & Control
- **EMV_TAG_PIN_TRY_COUNTER (0x9F17)**: PIN try counter
- **EMV_TAG_LAST_ONLINE_ATC (0x9F13)**: Last online ATC

#### Processing Information
- **EMV_TAG_PDOL (0x9F38)**: Processing Options Data Object List
- **EMV_TAG_AFL (0x94)**: Application File Locator
- **EMV_TAG_GPO_FMT1 (0x80)**: Get Processing Options response format 1

### 3. `emv_decode_response_tlv()`

Recursive parser for nested TLV structures:

```c
static bool emv_decode_response_tlv(const uint8_t* buff, uint8_t len, EmvApplication* app)
```

**Features:**
- Handles constructed TLV objects (nested structures)
- Recursive parsing of complex EMV responses
- Proper error handling for malformed data

**Constructed Object Detection:**
- If `(first_byte & 32) == 32`: Contains nested TLV data
- Recursively calls itself to parse nested content

### 4. `emv_decode_tl()`

Specialized parser for transaction logs using format templates:

```c
static bool emv_decode_tl(const uint8_t* buff, uint16_t len, const uint8_t* fmt, uint8_t fmt_len, EmvApplication* app)
```

**Purpose:**
- Parses transaction log entries using predefined format templates
- Format template defines the structure of log data
- Used specifically for EMV transaction history extraction

## Track Data Parsing

### Track 2 Data Processing

Special handling for Track 2 equivalent data:

```c
case EMV_TAG_TRACK_2_DATA:
case EMV_TAG_TRACK_2_EQUIV:
```

**Process:**
1. Search for 0xD0 delimiter separating PAN from expiry date
2. Extract PAN (Primary Account Number)
3. Extract expiration date in YYMM format
4. Convert 4-bit nibbles to ASCII representation
5. Handle termination characters properly

**Format:**
- PAN data followed by 0xD0 delimiter
- Expiry date in YYMM format
- Additional service code and discretionary data

## Error Handling

### `emv_response_error()`

Detects and handles EMV response errors:

```c
static bool emv_response_error(const uint8_t* buff, uint16_t len)
```

**Error Types:**
- **0x6C**: Wrong length - indicates required buffer size
- **0x61**: Bytes available - indicates more data available
- Other 6xxx status codes indicate various error conditions

## Data Extraction Features

### PAN (Primary Account Number) Extraction

Multiple sources for PAN data:
1. EMV_TAG_PAN (direct PAN tag)
2. EMV_TAG_TRACK_2_EQUIV (Track 2 data)
3. EMV_TAG_TRACK_2_DATA (alternative track format)

### Cardholder Name Processing

Special string handling:
- Null termination after specified length
- Space character (0x20) used as early terminator
- Prevents buffer overflow with length checking

### Transaction Log Parsing

Comprehensive transaction data extraction:
- Amount in various currency formats
- Date/time in EMV standard formats
- Country and currency codes
- Application Transaction Counter (ATC)

### Security Information

Critical security data extraction:
- PIN try counter (remaining PIN attempts)
- Application Interchange Profile (supported features)
- Last online ATC (fraud detection)

## Performance Considerations

### Efficient Parsing
- Single-pass parsing where possible
- Minimal memory copying
- Direct pointer manipulation for performance

### Memory Management
- Fixed-size buffers to prevent overflow
- Length validation for all data extraction
- Proper boundary checking

## Integration Points

### PDOL Preparation

```c
static void emv_prepare_pdol(APDU* dest, APDU* src)
```

Prepares Processing Options Data Object List for GET PROCESSING OPTIONS command:
- Parses PDOL template from card
- Builds appropriate request data
- Handles various PDOL tag requirements

### AFL Processing

Application File Locator processing for reading card data:
- Extracts SFI (Short File Identifier) numbers
- Determines record ranges to read
- Manages file access sequence

This TLV parser implementation provides a robust foundation for EMV card data extraction, handling the complex nested structure of EMV data while maintaining security and performance.
