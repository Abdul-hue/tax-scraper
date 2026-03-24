# Scraper Tool API Documentation

This document provides details for the backend APIs of the Scraper Tool.

**Base URL:** `http://localhost:8000`

---

## Core Endpoints

### 1. Module Info
- **Endpoint:** `/core/`
- **Method:** `GET`
- **Headers:** `None`
- **Body:** `None`
- **Expected Return:**
  ```json
  {
    "module": "core",
    "status": "active"
  }
  ```

### 2. Health Check
- **Endpoint:** `/core/health`
- **Method:** `GET`
- **Headers:** `None`
- **Body:** `None`
- **Expected Return:**
  ```json
  {
    "status": "ok"
  }
  ```

---

## Scraper Endpoints

### 1. ListenToTaxman Scraper
- **Endpoint:** `/scrapers/taxman`
- **Method:** `GET`
- **Query Parameters:**
  - `salary` (int, required): The salary amount.
  - `period` (str, default: "month"): Options: `year`, `month`, `4weeks`, `2weeks`, `week`, `day`, `hour`.
  - `tax_year` (str, default: "2025/26"): e.g., "2024/25".
  - `region` (str, default: "UK"): Options: `UK`, `Scotland`.
  - `age` (str, default: "under 65"): Options: `under 65`, `65-74`, `75 and over`.
  - `student_loan` (str, default: "No"): Options: `No`, `Plan 1`, `Plan 2`, `Plan 4`, `Postgraduate`.
  - `pension_amount` (float, default: 0): Amount or percentage.
  - `pension_type` (str, default: "£"): Options: `£`, `%`.
  - `allowances` (float, default: 0): Personal allowances.
  - `tax_code` (str, default: ""): Custom tax code.
  - `married` (bool, default: false): Married allowance flag.
  - `blind` (bool, default: false): Blind person's allowance flag.
  - `no_ni` (bool, default: false): No National Insurance flag.
- **Expected Return:**
  ```json
  {
    "config": { ... },
    "scraped_at": "ISO-8601 Timestamp",
    "url": "https://www.listentotaxman.com/...",
    "payslip": [
      {
        "label": "Gross Pay",
        "percent": "",
        "yearly": "£...",
        "monthly": "£...",
        "weekly": "£..."
      },
      ...
    ],
    "summary": { ... },
    "screenshot_url": "http://localhost:8000/static/screenshots/...",
    "error": null
  }
  ```

### 2. Council Tax Scraper
- **Endpoint:** `/scrapers/counciltax`
- **Method:** `GET`
- **Query Parameters:**
  - `postcode` (str, required): The UK postcode to look up.
- **Expected Return:**
  ```json
  {
    "postcode": "...",
    "scraped_at": "...",
    "properties": [
      {
        "address": "...",
        "band": "...",
        "annual_amount": 0.0,
        "monthly_amount": 0.0,
        "postcode": "..."
      },
      ...
    ],
    "screenshot_url": "...",
    "error": null
  }
  ```

### 3. Parkers Car Valuation Scraper
- **Endpoint:** `/scrapers/parkers`
- **Method:** `GET`
- **Query Parameters:**
  - `plate` (str, required): Vehicle registration plate.
- **Expected Return:**
  ```json
  {
    "plate": "...",
    "config": { ... },
    "scraped_at": "...",
    "reg_plate": "...",
    "make": "...",
    "model": "...",
    "year": "...",
    "vehicle_version": "...",
    "vehicle_full_name": "...",
    "vehicle_image": "...",
    "vehicle_details": { ... },
    "prices": {
      "private_low": "£...",
      "private_high": "£...",
      "dealer_low": "£...",
      "dealer_high": "£..."
    },
    "screenshot_url": "...",
    "error": null,
    "message": null
  }
  ```

### 4. Nationwide House Price Index Scraper
- **Endpoint:** `/scrapers/nationwide`
- **Method:** `GET`
- **Query Parameters:**
  - `region` (str, default: "Greater London"): UK region.
  - `postcode` (str, optional): Postcode.
  - `property_value` (int, default: 0): Initial property value.
  - `from_year` (int, required): Starting year.
  - `from_quarter` (int, default: 1): Starting quarter (1-4).
  - `to_year` (int, required): Target year.
  - `to_quarter` (int, default: 1): Target quarter (1-4).
- **Expected Return:**
  ```json
  {
    "scraped_at": "...",
    "from_label": "...",
    "from_value": "...",
    "to_label": "...",
    "to_value": "...",
    "percentage_change": "...",
    "description": "...",
    "screenshot_url": "...",
    "error": null
  }
  ```

### 5. LPS (Land & Property Services) Scraper
- **Endpoint:** `/scrapers/lps`
- **Method:** `GET`
- **Query Parameters:**
  - `search_type` (str, default: "postcode"): `postcode`, `street`, `property_id`.
  - `postcode` (str, optional): Postcode.
  - `property_number` (str, optional): House/Building number.
  - `street` (str, optional): Street name.
  - `town` (str, optional): Town.
  - `district_council` (str, optional): Council name.
  - `property_id` (str, optional): LPS Property ID.
  - `max_pages` (int, default: 3): Max pages to scrape.
- **Expected Return:**
  ```json
  {
    "scraped_at": "...",
    "search_type": "...",
    "total_found": 0,
    "pages_scraped": 0,
    "properties": [
      {
        "property_id": "...",
        "full_address": "...",
        "capital_value": "...",
        "total_nav": "..."
      },
      ...
    ],
    "property_details": [
      {
        "property_id": "...",
        "uprn": "...",
        "property_type": "...",
        "full_address": "...",
        "description": "...",
        "nav_non_exempt": "...",
        "nav_exempt": "...",
        "estimated_rate_bill": "...",
        "valuation_summaries": [ ... ],
        "error": ""
      },
      ...
    ],
    "screenshot_url": "...",
    "error": "",
    "success": true
  }
  ```

### 6. Land Registry Scraper
- **Endpoint:** `/scrapers/landregistry`
- **Method:** `GET`
- **Query Parameters:**
  - `username` (str, required): Land Registry username.
  - `password` (str, required): Land Registry password.
  - `customer_reference` (str, required): Reference for the order.
  - `title_number` (str, optional): Title number.
  - `flat` (str, optional): Flat number.
  - `house` (str, optional): House number/name.
  - `street` (str, optional): Street.
  - `town` (str, optional): Town.
  - `postcode` (str, optional): Postcode.
  - `order_register` (bool, default: true): Order title register PDF.
  - `order_title_plan` (bool, default: true): Order title plan PDF.
- **Expected Return:**
  ```json
  {
    "scraped_at": "...",
    "title_number": "...",
    "address": "...",
    "tenure": "...",
    "administered_by": "...",
    "customer_reference": "...",
    "register_url": "...",
    "title_plan_url": "...",
    "register_local_path": "...",
    "title_plan_local_path": "...",
    "register_data": {
      "a_register": { ... },
      "b_register": { ... },
      "c_register": { ... }
    },
    "title_plan_data": { ... },
    "screenshot_url": "...",
    "error": null
  }
  ```

### 7. IDU (Identity Verification) Scraper - Full Sync
- **Endpoint:** `/scrapers/idu`
- **Method:** `GET`
- **Query Parameters:**
  - `username`, `password` (str, required)
  - `forename`, `surname` (str, required)
  - `dd`, `mm`, `yyyy` (str, optional): Date of Birth.
  - `gender` (str, optional): `Male` or `Female`.
  - `house`, `street`, `town`, `postcode` (str, optional): Address details.
  - `email`, `mobile`, `landline` (str, optional): Contact details.
- **Expected Return:**
  ```json
  {
    "config": { ... },
    "scraped_at": "...",
    "search_id": "...",
    "verdict": "...",
    "score": "...",
    "date_of_search": "...",
    "summary_items": [
      {
        "category": "...",
        "label": "...",
        "status": "..."
      }
    ],
    "pep_entries": [
      {
        "match_score": "...",
        "name": "...",
        "country": "...",
        "reason": "..."
      }
    ],
    "screenshot_url": "...",
    "error": null
  }
  ```

### 8. IDU Scraper - Start OTP Flow
- **Endpoint:** `/scrapers/idu/start`
- **Method:** `POST`
- **Query Parameters:** (Same as IDU Full Sync)
- **Expected Return:**
  ```json
  {
    "session_id": "uuid-string",
    "status": "otp_required"
  }
  ```

### 9. IDU Scraper - Submit OTP
- **Endpoint:** `/scrapers/idu/submit-otp`
- **Method:** `POST`
- **Query Parameters:**
  - `session_id` (str, required)
  - `otp` (str, required)
- **Expected Return:**
  ```json
  {
    "status": "processing"
  }
  ```

### 10. IDU Scraper - Get Result
- **Endpoint:** `/scrapers/idu/result/{session_id}`
- **Method:** `GET`
- **Expected Return:**
  ```json
  {
    "status": "complete",
    "result": { ... (Same as IDU Full Sync) }
  }
  ```

---

## Static Files Endpoints

### 1. Serve Land Registry File
- **Endpoint:** `/files/landregistry/{filename}`
- **Method:** `GET`
- **Expected Return:** PDF File Content.

### 2. Serve Screenshot
- **Endpoint:** `/files/screenshots/{filename}`
- **Method:** `GET`
- **Expected Return:** PNG Image Content.
