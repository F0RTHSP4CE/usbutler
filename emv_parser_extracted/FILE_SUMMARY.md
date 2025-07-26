# EMV Implementation File Summary

## Core Protocol Implementation

### `lib/nfc/protocols/emv/emv.h`
**Primary EMV data structures and constants**
- `EmvApplication` - Complete EMV application data structure
- `EmvData` - Top-level EMV card data container
- `Transaction` - Individual transaction record structure
- `APDU` - Application Protocol Data Unit structure
- EMV tag definitions (EMV_TAG_*)
- Error codes and protocol constants

### `lib/nfc/protocols/emv/emv.c`
**EMV data management and serialization**
- Memory allocation/deallocation (`emv_alloc`, `emv_free`)
- Data copying and comparison (`emv_copy`, `emv_is_equal`)
- File I/O operations (`emv_load`, `emv_save`)
- UID and device name handling
- FlipperFormat serialization support

### `lib/nfc/protocols/emv/emv_poller.h`
**Public EMV poller interface**
- `EmvPoller` structure definition
- `EmvPollerEvent` - Event system for EMV operations
- `EmvPollerEventType` - Event type enumeration
- Public function declarations for EMV communication

### `lib/nfc/protocols/emv/emv_poller.c`
**High-level EMV communication state machine**
- EMV reading state machine implementation
- Event-driven callback system
- Card detection and protocol negotiation
- Integration with ISO14443-4A layer
- Public API implementation

### `lib/nfc/protocols/emv/emv_poller_i.h`
**Internal EMV poller definitions**
- `EmvPollerState` enumeration (Idle, SelectPPSE, etc.)
- Internal EMV poller structure
- Session state management
- Internal function declarations

### `lib/nfc/protocols/emv/emv_poller_i.c` ⭐ **CORE TLV PARSER**
**The heart of EMV data extraction - 794 lines of TLV parsing logic**

**Key Functions:**
- `emv_decode_tlv_tag()` - Extracts data based on EMV tag types (300+ lines)
- `emv_parse_tag()` - Parses TLV tag and length encoding
- `emv_decode_response_tlv()` - Recursive TLV structure parser
- `emv_decode_tl()` - Transaction log format parser
- `emv_prepare_pdol()` - PDOL preparation for card communication

**EMV Commands:**
- `emv_poller_select_ppse()` - SELECT PPSE command
- `emv_poller_select_application()` - SELECT application command
- `emv_poller_get_processing_options()` - GET PROCESSING OPTIONS
- `emv_poller_read_sfi_record()` - Read SFI records
- `emv_poller_read_afl()` - Read Application File Locator data
- `emv_poller_read_log_entry()` - Read transaction logs

**Data Extraction:**
- PAN (Primary Account Number) from multiple sources
- Track 1/2 data parsing with delimiter handling
- Cardholder name extraction with proper termination
- Transaction history with amounts, dates, currencies
- Security data (PIN counters, ATC values)

### `lib/nfc/protocols/emv/emv_poller_defs.h`
**EMV protocol definitions and constants**
- Additional EMV tag definitions
- Protocol-specific constants
- Communication parameters

## Application Support Layer

### `applications/main/nfc/helpers/nfc_emv_parser.h`
**EMV data lookup and resolution interface**
- Function declarations for name resolution
- AID to application name mapping
- Currency code to name conversion
- Country code to name conversion

### `applications/main/nfc/helpers/nfc_emv_parser.c`
**EMV lookup table implementation**
- `nfc_emv_parser_get_aid_name()` - AID to application name
- `nfc_emv_parser_get_currency_name()` - Currency code resolution
- `nfc_emv_parser_get_country_name()` - Country code resolution
- File-based lookup table parsing
- Storage system integration

### `applications/main/nfc/helpers/protocol_support/emv/emv.h`
**EMV protocol support header**
- Submenu index definitions
- Integration declarations
- Protocol support interface

### `applications/main/nfc/helpers/protocol_support/emv/emv.c`
**EMV protocol framework integration**
- NFC application integration
- Scene management callbacks
- Poller callback implementation
- Menu system integration
- Success/failure handling

### `applications/main/nfc/helpers/protocol_support/emv/emv_render.h`
**EMV data rendering interface**
- Function declarations for data formatting
- Rendering utility interfaces
- Display format specifications

### `applications/main/nfc/helpers/protocol_support/emv/emv_render.c`
**EMV data formatting and display**
- `nfc_render_emv_info()` - Complete EMV info rendering
- `nfc_render_emv_pan()` - PAN formatting with spacing
- `nfc_render_emv_name()` - Cardholder name formatting
- `nfc_render_emv_application()` - Application info display
- `nfc_render_emv_transactions()` - Transaction history formatting
- `nfc_render_emv_currency()` - Currency code display
- `nfc_render_emv_country()` - Country code display
- Card number formatting with proper spacing
- Transaction data with date/time formatting

## User Interface Components

### `applications/main/nfc/scenes/nfc_scene_emv_transactions.c`
**Transaction history display scene**
- Transaction list UI implementation
- Widget-based transaction display
- Scene lifecycle management (enter/exit/event)
- Integration with EMV render functions

### `applications/main/nfc/plugins/supported_cards/emv.c`
**EMV card detection and basic display plugin**
- Currency name resolution with storage
- Country name resolution with storage
- AID name resolution with storage
- Integration with card detection system
- Basic EMV card info display

## Data Flow Summary

1. **Detection**: `emv_poller.c` detects EMV card via ISO14443-4A
2. **Communication**: State machine executes EMV commands (SELECT PPSE, etc.)
3. **Parsing**: `emv_poller_i.c` TLV parser extracts all card data
4. **Storage**: `emv.c` manages data structures and serialization
5. **Lookup**: `nfc_emv_parser.c` resolves codes to human-readable names
6. **Display**: `emv_render.c` formats data for user presentation
7. **UI**: Scene and plugin files provide user interface

## Most Important Files for EMV Parsing

1. **`emv_poller_i.c`** - Core TLV parsing and data extraction (794 lines)
2. **`emv.h`** - Data structures and EMV tag definitions
3. **`emv_render.c`** - Data formatting and display logic
4. **`nfc_emv_parser.c`** - Lookup table support for readable names

These four files contain the complete EMV card data extraction and processing logic, from low-level TLV parsing to high-level data presentation.
