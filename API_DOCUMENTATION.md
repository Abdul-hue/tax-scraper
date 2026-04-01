# Scraper Tool API Documentation

This document reflects the current backend routes and the way the existing React frontend calls them and consumes their responses.

**Direct backend base URL:** `http://localhost:8000`

**Frontend dev usage:** the React app calls these routes through `/api/...`, and Vite rewrites `/api` to `http://localhost:8000`.

---

## Common behavior

### Request format
- All scraper inputs are passed as query parameters.
- Even the `POST` routes currently use query parameters and send an empty body from the frontend.

### Response format
- Most scraper routes return JSON generated from scraper result models.
- Screenshot and file links in responses are relative app paths such as `/api/files/screenshots/...` and `/api/files/landregistry/...`.

### Error handling
- `GET /scrapers/taxman`
- `GET /scrapers/counciltax`
- `GET /scrapers/parkers`
- `GET /scrapers/nationwide`
- `GET /scrapers/lps`
- `GET /scrapers/landregistry`
- `GET /scrapers/idu`

The routes above all pass through a shared wrapper:

```json
{
  "rule": "if response.error is truthy -> HTTP 500, otherwise HTTP 200"
}
```

That means business-state responses such as Parkers `not_found` also become non-2xx responses because `error` is populated.

### Frontend response handling
- The UI renders successful responses directly from `response.data`.
- For most non-2xx failures, the UI shows `err.response?.data?.detail || err.message`.
- Because scraper failures usually return an `error` field instead of FastAPI `detail`, the current UI often surfaces only the HTTP error unless the caller explicitly inspects the response body.
- IDU OTP flow is different: it polls a status endpoint and branches on `processing`, `awaiting_otp`, `complete`, and `error`.

---

## Core endpoints

### 1. Module Info
- **Endpoint:** `/core/`
- **Method:** `GET`
- **Body:** none
- **Response:**
  ```json
  {
    "module": "core",
    "status": "active"
  }
  ```

### 2. Health Check
- **Endpoint:** `/core/health`
- **Method:** `GET`
- **Body:** none
- **Response:**
  ```json
  {
    "status": "ok"
  }
  ```

---

## Frontend request map

These are the exact payload shapes currently sent by `frontend/src/App.jsx`.

### 1. ListenToTaxman
```http
GET /api/scrapers/taxman?salary=3000&period=month&tax_year=2025%2F26&region=UK&age=under+65&student_loan=No&pension_amount=0&pension_type=%C2%A3&allowances=0&tax_code=&married=false&blind=false&no_ni=false
```

### 2. Council Tax
```http
GET /api/scrapers/counciltax?postcode=LS278RR
```

### 3. Parkers
```http
GET /api/scrapers/parkers?plate=BD51SMM
```

### 4. Nationwide
```http
GET /api/scrapers/nationwide?property_value=300000&from_year=2020&from_quarter=1&to_year=2025&to_quarter=1&region=Greater+London
```

The frontend sends one of:
- `region=<region>`
- `postcode=<postcode>`
- `region=UK`

### 5. LPS
```http
GET /api/scrapers/lps?search_type=postcode&postcode=BT1+5GS&property_number=&max_pages=3&fetch_details=true
```

Important notes:
- The frontend currently sends `fetch_details=true`.
- The backend route does not accept or use `fetch_details`, so it is ignored.
- The current UI only uses postcode-style LPS searches.

### 6. Land Registry
```http
GET /api/scrapers/landregistry?username=...&password=...&customer_reference=...&title_number=...&flat=...&house=...&street=...&town=...&postcode=...&order_register=true&order_title_plan=true
```

### 7. IDU start flow
```http
POST /api/scrapers/idu/start?username=...&password=...&forename=...&middlename=...&surname=...&dd=...&mm=...&yyyy=...&gender=...&reference=...&house=...&street=...&town=...&postcode=...&email=...&email2=...&mobile=...&mobile2=...&landline=...&landline2=...
Body: empty
```

### 8. IDU submit OTP
```http
POST /api/scrapers/idu/submit-otp?session_id=<uuid>&otp=<code>
Body: empty
```

### 9. IDU poll result
```http
GET /api/scrapers/idu/result/<session_id>
```

---

## Scraper endpoints

### 1. ListenToTaxman scraper
- **Endpoint:** `/scrapers/taxman`
- **Method:** `GET`
- **Query parameters:**
  - `salary` (`int`, required)
  - `period` (`str`, default `"month"`): `year`, `month`, `4weeks`, `2weeks`, `week`, `day`, `hour`
  - `tax_year` (`str`, default `"2025/26"`)
  - `region` (`str`, default `"UK"`): `UK`, `Scotland`
  - `age` (`str`, default `"under 65"`): `under 65`, `65-74`, `75 and over`
  - `student_loan` (`str`, default `"No"`): `No`, `Plan 1`, `Plan 2`, `Plan 4`, `Postgraduate`
  - `pension_amount` (`float`, default `0`)
  - `pension_type` (`str`, default `"£"`): `£`, `%`
  - `allowances` (`float`, default `0`)
  - `tax_code` (`str`, default `""`)
  - `married` (`bool`, default `false`)
  - `blind` (`bool`, default `false`)
  - `no_ni` (`bool`, default `false`)
- **Success response:**
  ```json
  {
    "config": {
      "salary": 3000,
      "salary_period": "month",
      "tax_year": "2025/26",
      "region": "UK",
      "age": "under 65",
      "student_loan": "No",
      "pension_amount": 0,
      "pension_type": "£",
      "allowances": 0,
      "tax_code": "",
      "married": false,
      "blind": false,
      "no_ni": false
    },
    "scraped_at": "2026-03-31T12:00:00Z",
    "url": "https://www.listentotaxman.com",
    "payslip": [
      {
        "label": "Gross Pay",
        "percent": "",
        "yearly": "£36,000.00",
        "monthly": "£3,000.00",
        "weekly": "£692.31"
      }
    ],
    "summary": {
      "Net Wage": {
        "percent": "",
        "yearly": "£...",
        "monthly": "£...",
        "weekly": "£..."
      }
    },
    "screenshot_url": "/api/files/screenshots/taxman_20260331_120000.png",
    "error": null
  }
  ```
- **Frontend uses:** `payslip`, `screenshot_url`

### 2. Council Tax scraper
- **Endpoint:** `/scrapers/counciltax`
- **Method:** `GET`
- **Query parameters:**
  - `postcode` (`str`, required)
- **Success response:**
  ```json
  {
    "postcode": "LS278RR",
    "scraped_at": "2026-03-31T12:00:00Z",
    "properties": [
      {
        "address": "1 Example Street",
        "band": "C",
        "annual_amount": 1842.0,
        "monthly_amount": 153.5,
        "local_authority": "",
        "postcode": "LS278RR"
      }
    ],
    "screenshot_url": "/api/files/screenshots/counciltax_20260331_120000.png",
    "error": null
  }
  ```
- **Failure shape:** same top-level keys, with `properties: []` and `error` populated
- **Frontend uses:** `properties[].address`, `properties[].band`, `properties[].monthly_amount`, `screenshot_url`

### 3. Parkers car valuation scraper
- **Endpoint:** `/scrapers/parkers`
- **Method:** `GET`
- **Query parameters:**
  - `plate` (`str`, required)
- **Success response:**
  ```json
  {
    "plate": "BD51SMM",
    "config": {
      "plate": "BD51SMM"
    },
    "scraped_at": "2026-03-31T12:00:00Z",
    "reg_plate": "BD51SMM",
    "make": "Ford",
    "model": "Focus",
    "year": "2019",
    "vehicle_version": "1.0 EcoBoost 125 ST-Line",
    "vehicle_full_name": "Ford Focus 1.0 EcoBoost 125 ST-Line 2019",
    "vehicle_image": "https://...",
    "vehicle_details": {
      "Fuel type": "Petrol",
      "Transmission": "Manual"
    },
    "prices": {
      "private_low": "£8,500",
      "private_high": "£9,250",
      "dealer_low": "£9,750",
      "dealer_high": "£10,500",
      "part_exchange": "£8,900"
    },
    "screenshot_url": "/api/files/screenshots/parkers_20260331_120000.png",
    "error": null,
    "message": null
  }
  ```
- **Known non-success payloads:**
  ```json
  {
    "plate": "BD51SMM",
    "reg_plate": "BD51SMM",
    "scraped_at": "2026-03-31T12:00:00Z",
    "error": "not_found",
    "message": "not_found"
  }
  ```
- **Important behavior:** because `error` is set, this route is returned as HTTP 500 by the wrapper even for `not_found`
- **Frontend uses:** `make`, `reg_plate`, `vehicle_full_name`, `vehicle_image`, `vehicle_details`, `prices`, `screenshot_url`

### 4. Nationwide house price index scraper
- **Endpoint:** `/scrapers/nationwide`
- **Method:** `GET`
- **Query parameters:**
  - `region` (`str`, default `"Greater London"`)
  - `postcode` (`str`, default `""`)
  - `property_value` (`int`, default `0`)
  - `from_year` (`int`, default `0`)
  - `from_quarter` (`int`, default `1`)
  - `to_year` (`int`, default `0`)
  - `to_quarter` (`int`, default `1`)
- **Location logic:**
  - If `postcode` is provided, postcode mode is used.
  - Else if `region` is provided and not equal to `UK`, region mode is used.
  - Else UK average mode is used.
- **Success response:**
  ```json
  {
    "scraped_at": "2026-03-31T12:00:00Z",
    "from_label": "Q1 2020",
    "from_value": "£300,000",
    "to_label": "Q1 2025",
    "to_value": "£365,000",
    "percentage_change": "+21.67%",
    "description": "Based on Nationwide HPI data",
    "screenshot_path": null,
    "screenshot_url": "/api/files/screenshots/nationwide_20260331_120000.png",
    "error": null
  }
  ```
- **Frontend uses:** `description`, `from_label`, `from_value`, `to_label`, `to_value`, `percentage_change`, `screenshot_url`

### 5. LPS scraper
- **Endpoint:** `/scrapers/lps`
- **Method:** `GET`
- **Query parameters accepted by the backend route:**
  - `search_type` (`str`, default `"postcode"`)
  - `postcode` (`str`, default `""`)
  - `property_number` (`str`, default `""`)
  - `adv_property_number` (`str`, default `""`)
  - `street` (`str`, default `""`)
  - `town` (`str`, default `""`)
  - `district_council` (`str`, default `""`)
  - `property_id` (`str`, default `""`)
  - `max_pages` (`int`, default `3`)
- **Search behavior:**
  - `search_type == "postcode"` uses postcode search
  - any other value falls into advanced search mode in the scraper
- **Success response:**
  ```json
  {
    "scraped_at": "2026-03-31T12:00:00Z",
    "search_type": "postcode",
    "total_found": 2,
    "pages_scraped": 1,
    "properties": [
      {
        "property_id": "123456",
        "full_address": "1 Example Street, Belfast",
        "capital_value": "£150,000",
        "total_nav": ""
      }
    ],
    "property_details": [
      {
        "property_id": "123456",
        "uprn": "100010001",
        "property_type": "Domestic",
        "full_address": "1 Example Street, Belfast",
        "description": "",
        "nav_non_exempt": "",
        "nav_exempt": "",
        "estimated_rate_bill": "£1,234.56",
        "ot_other": "",
        "in_industrial": "",
        "sr_sports": "",
        "ft_freight": "",
        "ex_exempt": "",
        "valuation_summaries": [
          {
            "num": "1",
            "floor": "Ground",
            "description_use": "Shop",
            "area": "20",
            "rate": "100",
            "distinguishment": ""
          }
        ],
        "error": ""
      }
    ],
    "screenshot_url": "/api/files/screenshots/lps_20260331_120000.png",
    "error": "",
    "success": true
  }
  ```
- **Failure shape from service layer:**
  ```json
  {
    "error": "some error message",
    "results": []
  }
  ```
- **Frontend uses:** `total_found`, `pages_scraped`, `properties`, `property_details`, `screenshot_url`

### 6. Land Registry scraper
- **Endpoint:** `/scrapers/landregistry`
- **Method:** `GET`
- **Query parameters:**
  - `username` (`str`, required)
  - `password` (`str`, required)
  - `customer_reference` (`str`, required)
  - `title_number` (`str`, default `""`)
  - `flat` (`str`, default `""`)
  - `house` (`str`, default `""`)
  - `street` (`str`, default `""`)
  - `town` (`str`, default `""`)
  - `postcode` (`str`, default `""`)
  - `order_register` (`bool`, default `true`)
  - `order_title_plan` (`bool`, default `true`)
- **Lookup behavior:**
  - You can search directly by `title_number`.
  - If `title_number` is blank, the scraper uses the address fields.
- **Success response:**
  ```json
  {
    "scraped_at": "2026-03-31T12:00:00Z",
    "title_number": "SGL123456",
    "address": "1 Example Street, London",
    "tenure": "Freehold",
    "administered_by": "Gloucester Office",
    "customer_reference": "REF-001",
    "register_url": "https://...",
    "title_plan_url": "https://...",
    "register_local_path": "/api/files/landregistry/SGL123456_register_20260331_120000.pdf",
    "title_plan_local_path": "/api/files/landregistry/SGL123456_title_plan_20260331_120000.pdf",
    "register_data": {
      "document_type": "register",
      "title_number": "SGL123456",
      "edition_date": "01.01.2024",
      "issued_on": "31 March 2026",
      "search_date": "31 March 2026",
      "a_register": {
        "tenure": "Freehold",
        "property_address": "1 Example Street, London",
        "county": "GREATER LONDON",
        "district": "CITY OF WESTMINSTER",
        "lease_date": "",
        "lease_term": "",
        "lease_rent": "",
        "lease_parties": []
      },
      "b_register": {
        "title_class": "Title absolute",
        "proprietor": "JOHN SMITH",
        "price_paid": "£450,000",
        "price_paid_date": "1 January 2020",
        "restrictions": []
      },
      "c_register": {
        "charge_count": 1,
        "charges": [
          {
            "lender": "BANK PLC",
            "company_reg": "",
            "charge_date": "1 January 2020",
            "lender_address": "London"
          }
        ]
      },
      "parse_error": null
    },
    "title_plan_data": {
      "document_type": "title_plan",
      "title_number": "SGL123456",
      "issued_on": "31 March 2026",
      "land_registry_office": "Gloucester Office",
      "map_note": "Title Plan page 2 is a raster image. Boundary coordinates are not extractable via PDF text parsing.",
      "parse_error": null
    },
    "screenshot_url": "/api/files/screenshots/landregistry_20260331_120000.png",
    "error": null
  }
  ```
- **Known non-success value:** `error: "no_results"`
- **Frontend uses:** `title_number`, `address`, `tenure`, `customer_reference`, `register_local_path`, `title_plan_local_path`, `register_data.a_register`, `register_data.b_register`, `register_data.c_register`, `title_plan_data`, `screenshot_url`

### 7. IDU full sync scraper
- **Endpoint:** `/scrapers/idu`
- **Method:** `GET`
- **Query parameters:**
  - required: `username`, `password`, `forename`, `surname`
  - optional: `dd`, `mm`, `yyyy`, `gender`, `middlename`, `reference`
  - optional address fields: `house`, `street`, `town`, `postcode`
  - optional contact fields: `email`, `email2`, `mobile`, `mobile2`, `landline`, `landline2`
- **Actual response shape from `to_dict()`:**
  ```json
  {
    "scraped_at": "2026-03-31 12:00:00",
    "search_id": "123456",
    "verdict": "PASS",
    "score": "8",
    "date_of_search": "31/03/2026",
    "summary_items": [
      {
        "category": "Identity",
        "label": "Address verification",
        "status": "match"
      }
    ],
    "address_detail": {},
    "credit_active": {},
    "dob_verification": {},
    "mortality": {},
    "gone_away": {},
    "pep_entries": [
      {
        "match_score": "",
        "name": "",
        "aliases": [],
        "last_updated": "",
        "addresses": [],
        "country": "",
        "position": "",
        "reason": ""
      }
    ],
    "sanction_result": "",
    "ccj": {},
    "insolvency": {},
    "company_director": {},
    "search_activity": {},
    "address_links": [],
    "property_detail": {},
    "screenshot_url": null,
    "error": null
  }
  ```
- **Important note:** the IDU result model contains `config`, but the current `to_dict()` does not expose it, so `config` is not in the API response
- **Frontend uses:** `verdict`, `score`, `search_id`, `date_of_search`, `summary_items`, `pep_entries`, `address_detail`, `credit_active`, `dob_verification`, `property_detail`, `ccj`, `insolvency`, `company_director`, `address_links`, `screenshot_url`

### 8. IDU scraper start OTP flow
- **Endpoint:** `/scrapers/idu/start`
- **Method:** `POST`
- **Request body:** none
- **Query parameters:** same as IDU full sync
- **Actual response:**
  ```json
  {
    "session_id": "uuid-string",
    "status": "processing"
  }
  ```
- **Important note:** this route does not return `otp_required`; the frontend starts polling immediately after receiving `processing`

### 9. IDU scraper submit OTP
- **Endpoint:** `/scrapers/idu/submit-otp`
- **Method:** `POST`
- **Request body:** none
- **Query parameters:**
  - `session_id` (`str`, required)
  - `otp` (`str`, required)
- **Success response:**
  ```json
  {
    "status": "processing"
  }
  ```
- **Failure response:**
  ```json
  {
    "error": "Session not found or already closed"
  }
  ```

### 10. IDU scraper poll result
- **Endpoint:** `/scrapers/idu/result/{session_id}`
- **Method:** `GET`
- **Possible responses:**
  ```json
  {
    "status": "processing"
  }
  ```

  ```json
  {
    "status": "awaiting_otp"
  }
  ```

  ```json
  {
    "status": "complete",
    "result": {
      "scraped_at": "2026-03-31 12:00:00",
      "search_id": "123456",
      "verdict": "PASS",
      "score": "8",
      "date_of_search": "31/03/2026",
      "summary_items": [],
      "address_detail": {},
      "credit_active": {},
      "dob_verification": {},
      "mortality": {},
      "gone_away": {},
      "pep_entries": [],
      "sanction_result": "",
      "ccj": {},
      "insolvency": {},
      "company_director": {},
      "search_activity": {},
      "address_links": [],
      "property_detail": {},
      "screenshot_url": null,
      "error": null
    }
  }
  ```

  ```json
  {
    "status": "error",
    "message": "Session not found"
  }
  ```

---

## Static file endpoints

### 1. Serve Land Registry PDF
- **Endpoint:** `/files/landregistry/{filename}`
- **Method:** `GET`
- **Response:** inline PDF file content

### 2. Serve screenshot
- **Endpoint:** `/files/screenshots/{filename}`
- **Method:** `GET`
- **Response:** inline PNG image content
