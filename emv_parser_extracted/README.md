# EMV Card Data Parsing Implementation

This directory contains the high-level EMV (Europay, Mastercard, Visa) card parsing and data extraction implementation extracted from the Unleashed Firmware project.

## Overview

The EMV implementation provides a complete system for reading and parsing EMV payment cards, extracting various types of card data including:

- **Card Information**: PAN (Primary Account Number), cardholder name, expiration dates
- **Application Data**: AID (Application Identifier), application names and labels
- **Transaction History**: Transaction logs with amounts, dates, currencies, and countries
- **Security Information**: PIN try counters, application interchange profiles
- **Metadata**: Currency codes, country codes, effective dates

## Architecture

### Core Library (`lib/nfc/protocols/emv/`)

1. **emv.h / emv.c** - Main EMV data structures and basic operations
   - `EmvData` structure containing all parsed card data
   - `EmvApplication` structure with detailed application information
   - Basic memory management and serialization functions

2. **emv_poller.h / emv_poller.c** - High-level EMV communication interface
   - Card detection and protocol handling
   - State machine for EMV reading process
   - Event-based callback system

3. **emv_poller_i.h / emv_poller_i.c** - Internal EMV parsing implementation
   - **TLV (Tag-Length-Value) parsing engine**
   - EMV command implementations (SELECT PPSE, GET PROCESSING OPTIONS, etc.)
   - Card data extraction from various EMV files (SFI records)

4. **emv_poller_defs.h** - EMV protocol definitions and constants

### Application Support (`applications/main/nfc/helpers/`)

1. **nfc_emv_parser.h / nfc_emv_parser.c** - Lookup tables and name resolution
   - AID to application name mapping
   - Currency code to currency name mapping
   - Country code to country name mapping

2. **protocol_support/emv/** - UI and rendering support
   - **emv_render.h / emv_render.c** - Data formatting and display functions
   - **emv.h / emv.c** - Integration with NFC application framework

### UI Components

1. **scenes/nfc_scene_emv_transactions.c** - Transaction history display
2. **plugins/supported_cards/emv.c** - EMV card detection and basic info display

## Key Features

### TLV Data Parsing

The core of the EMV implementation is the TLV (Tag-Length-Value) parser in `emv_poller_i.c`:

- **`emv_parse_tag()`** - Parses EMV TLV tags and lengths
- **`emv_decode_tlv_tag()`** - Extracts specific data based on EMV tag types
- **`emv_decode_response_tlv()`** - Recursive parser for nested TLV structures
- **`emv_decode_tl()`** - Transaction log parsing using format templates

### EMV Tag Support

The implementation supports numerous EMV tags including:

- **Card Data**: PAN (0x5A), Cardholder Name (0x5F20), Expiration Date (0x5F24)
- **Track Data**: Track 1 (0x56) and Track 2 (0x57) equivalent data
- **Application Info**: AID (0x4F), Application Label (0x50), Application Name (0x9F12)
- **Transaction Data**: Amount (0x9F02), Date (0x9A), Time (0x9F21), Currency (0x5F2A)
- **Security**: PIN Try Counter (0x9F17), ATC (0x9F36)

### EMV Communication Flow

1. **SELECT PPSE** - Selects Payment System Environment
2. **SELECT APPLICATION** - Selects specific payment application
3. **GET PROCESSING OPTIONS** - Retrieves Application File Locator (AFL)
4. **READ APPLICATION DATA** - Reads data from SFI (Short File Identifier) records
5. **READ TRANSACTION LOGS** - Extracts transaction history if available

### Data Extraction Capabilities

- **Primary Account Number (PAN)** extraction from multiple sources
- **Cardholder name** parsing with proper string termination
- **Transaction history** with full details (amount, date, time, currency, country)
- **Application information** including names, labels, and identifiers
- **Security counters** and interchange profiles
- **Effective and expiration dates** for cards

## File Structure

```
emv_parser_extracted/
├── lib/nfc/protocols/emv/           # Core EMV protocol implementation
│   ├── emv.h                        # Main EMV data structures
│   ├── emv.c                        # EMV data management
│   ├── emv_poller.h                 # Public EMV poller interface
│   ├── emv_poller.c                 # EMV poller implementation
│   ├── emv_poller_i.h              # Internal EMV structures
│   ├── emv_poller_i.c              # TLV parsing and command implementation
│   └── emv_poller_defs.h           # EMV constants and definitions
├── applications/main/nfc/helpers/
│   ├── nfc_emv_parser.h            # EMV lookup functions
│   ├── nfc_emv_parser.c            # AID/currency/country name resolution
│   └── protocol_support/emv/       # EMV rendering and UI support
│       ├── emv.h                   # EMV protocol support header
│       ├── emv.c                   # EMV protocol support implementation
│       ├── emv_render.h            # EMV data rendering functions
│       └── emv_render.c            # EMV data formatting implementation
├── applications/main/nfc/scenes/
│   └── nfc_scene_emv_transactions.c # Transaction history UI
└── applications/main/nfc/plugins/supported_cards/
    └── emv.c                       # EMV card detection plugin
```

## Key Data Structures

### EmvApplication
Contains all parsed EMV application data:
- Card numbers, names, dates
- Application identifiers and labels
- Transaction history (up to 16 transactions)
- Security information
- Currency and country codes

### EmvData
Top-level structure containing:
- ISO14443-4A data (NFC communication layer)
- EmvApplication data (parsed EMV information)

### Transaction
Individual transaction record with:
- ATC (Application Transaction Counter)
- Amount, currency, country
- Date and time information

## Usage

This implementation provides a complete EMV parsing system that can:

1. **Detect EMV cards** through the NFC interface
2. **Extract comprehensive card data** including sensitive information
3. **Parse transaction histories** when available
4. **Resolve application names** from AID databases
5. **Format data for display** with proper currency and country names

The code is designed to be modular and can be adapted for various EMV card analysis and research purposes while respecting security and privacy considerations.

## Security Considerations

This implementation extracts various types of payment card data. When using this code:

- Ensure compliance with applicable laws and regulations
- Respect cardholder privacy and data protection requirements
- Use only for authorized research, security analysis, or legitimate purposes
- Be aware that some extracted data may be sensitive or regulated

## Dependencies

The implementation depends on:
- ISO14443-4A NFC communication layer
- Flipper Zero hardware abstraction layer (FURI)
- Storage system for lookup tables
- Basic C standard library functions
