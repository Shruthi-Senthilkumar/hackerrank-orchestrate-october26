# Extracted image facts (Phase 4 task 5, D14)

Agreed facts for every image evidence file, produced by OCR grounding plus two Gemini readers (code/audit/evidence/image_reader.py). Committed here so the submission can be reviewed and reproduced without any further model call -- the live cache itself (.cache/) is git-ignored and not part of code.zip.

D16 re-check: SECONDARY_IDENTIFIER or PRODUCT_TELEMETRY found in any image? No -- D16 still holds.

## Per-image summary

| file_id | document_type | facts_extracted | grounded | dropped | disagreements | linker rules used | cases touched |
|---|---|---|---|---|---|---|---|
| evidence_04 | console_screenshot | 20 | 12 | 8 | 1 | activity, same_document | 1 |
| evidence_09 | console_screenshot | 10 | 8 | 2 | 0 | activity, same_document | 1 |
  - **flagged**: second reader unavailable; using primary (grounded) only
| evidence_14 | console_screenshot | 8 | 6 | 2 | 0 | activity, same_document, trace_correlation | 2 |
  - **flagged**: second reader unavailable; using primary (grounded) only
| evidence_19 | console_screenshot | 6 | 5 | 1 | 0 | activity | 1 |
  - **flagged**: second reader unavailable; using primary (grounded) only
| evidence_23 | console_screenshot | 11 | 11 | 0 | 0 | activity, same_document | 2 |
  - **flagged**: second reader unavailable; using primary (grounded) only
| evidence_28 | support_record | 13 | 10 | 3 | 0 | (none -- never linked to any case) | 0 |
| evidence_32 | console_screenshot | 11 | 11 | 0 | 0 | activity | 1 |
  - **flagged**: second reader unavailable; using primary (grounded) only
| evidence_37 | console_screenshot | 10 | 9 | 1 | 0 | identity_key | 1 |
  - **flagged**: second reader unavailable; using primary (grounded) only
| evidence_42 | console_screenshot | 7 | 2 | 5 | 0 | (none -- never linked to any case) | 0 |
  - **flagged**: second reader unavailable; using primary (grounded) only
| evidence_46 | object_storage_browser | 11 | 3 | 8 | 0 | (none -- never linked to any case) | 0 |
  - **flagged**: second reader unavailable; using primary (grounded) only
| evidence_60 | console_screenshot | 6 | 6 | 0 | 0 | activity | 1 |
  - **flagged**: second reader unavailable; using primary (grounded) only

## Agreed facts, in full

### evidence_04

```json
{'document_type': 'console_screenshot', 'system_id': 'unknown', 'resource_ids': ['account_5762', 'support_9538'], 'identifiers': [{'kind': 'name', 'value': 'Haruka Sato'}, {'kind': 'email', 'value': 'haruka.s1838@zoho.com'}, {'kind': 'phone', 'value': '+81 90 7610 2507'}], 'observed_state_words': ['Silver', 'Delivered', 'Returned'], 'timestamps': ['24 Sep 2026 09:14 JST', '12 Sep 2026', '18 Sep', '28 Aug 2026', '03 Sep', '12 Jan 2024', '24 Sep', '22 Sep', '18 Sep', '03 Sep', '28 Aug']}
```

### evidence_09

```json
{'document_type': 'console_screenshot', 'system_id': 'search_service', 'resource_ids': ['search_428', 'search_1874'], 'identifiers': [{'kind': 'name', 'value': 'Gabriel Silva'}, {'kind': 'email', 'value': 'g.silva76@gmail.com'}, {'kind': 'email', 'value': 'g.silva76.jr@gmail.com'}, {'kind': 'name', 'value': 'Aditi Jain'}], 'observed_state_words': [], 'timestamps': ['01 Sep 2026 06:00:14 UTC', '05:58:21 UTC', '05:55:03 UTC', '2026-09-01T05:58:21Z', '06:00:14', '05:42:03', '05:31:18']}
```

### evidence_14

```json
{'document_type': 'console_screenshot', 'system_id': 'integration_service', 'resource_ids': ['data_flow_1121', 'data_flow_9846'], 'identifiers': [{'kind': 'email', 'value': 'jain.aditi@gmail.com'}, {'kind': 'email', 'value': 'lucia-torres@gmail.com'}], 'observed_state_words': ['Healthy', 'Continuous', 'Continuous sync'], 'timestamps': ['07 Aug 2026 08:00 UTC', '07:59:42', '07:59:36', '07:59:28', '07:59:13', '07:59:42', '07:58:10', '07:56:44', '07:55:02']}
```

### evidence_19

```json
{'document_type': 'console_screenshot', 'system_id': 'analytics_platform', 'resource_ids': ['analytics_7438'], 'identifiers': [{'kind': 'name', 'value': 'Omar Darwish'}, {'kind': 'email', 'value': 'darwish.omar@icloud.com'}], 'observed_state_words': ['Returning shopper'], 'timestamps': ['13 Jul 2026 14:22 UTC', '21 Apr 2026 09:14 UTC', '13 Jul', '08 Jul', '30 Jun', '22 Jun']}
```

### evidence_23

```json
{'document_type': 'console_screenshot', 'system_id': 'export_service', 'resource_ids': ['export_1261', 'export_1260', 'export_1259', 'export_1258'], 'identifiers': [{'kind': 'email', 'value': 'marcus.lee@northstar.shop'}, {'kind': 'email', 'value': 'ingrid.dahl@outlook.com'}, {'kind': 'email', 'value': 'sara.kim@northstar.shop'}, {'kind': 'email', 'value': 'daniel.park@northstar.shop'}, {'kind': 'hash', 'value': 'SHA-256 - 41ca09...'}], 'observed_state_words': ['Collecting', 'Ready', 'Packaging', 'Ready'], 'timestamps': ['20 Jun 14:18 UTC', '18 Jun 06:42 UTC', '17 Jun 11:03 UTC', '16 Jun 09:27 UTC', '18 Jun 2026 06:42 UTC', '25 Jun 2026 06:42 UTC', '06:46', '06:45', '06:43', '06:42']}
```

### evidence_28

```json
{'document_type': 'support_record', 'system_id': 'support_platform', 'resource_ids': [], 'identifiers': [{'kind': 'name', 'value': 'Kofi Agyeman'}, {'kind': 'email', 'value': 'kagyeman8947@fastmail.com'}, {'kind': 'name', 'value': 'Maya Chen'}], 'observed_state_words': ['Normal priority', 'In transit'], 'timestamps': ['26 May', '09:12', '09:13', '09:28', '09:35', '22 May', '23 May', '24 May 07:46', '24 May 08:15', '26 May 2026']}
```

### evidence_32

```json
{'document_type': 'console_screenshot', 'system_id': 'backup_service', 'resource_ids': ['backup_9291', 'backup_9288', 'backup_9287', 'backup_9286', 'backup_9281'], 'identifiers': [{'kind': 'email', 'value': 'bluepeakco@outlook.com'}, {'kind': 'email', 'value': 'miller.logistics@company.com'}, {'kind': 'email', 'value': 'areed1433@gmail.com'}, {'kind': 'email', 'value': 'summit-retail@company.com'}], 'observed_state_words': ['Healthy', 'Verified', 'Completed'], 'timestamps': ['26 Apr 02:00', '29 Mar 2026', '26 Jul 2026', '25 Apr', '24 Apr', '22 Apr']}
```

### evidence_37

```json
{'document_type': 'console_screenshot', 'system_id': 'security_service', 'resource_ids': ['audit_record_003', 'audit_record_002', 'audit_record_001', 'audit_record_006', 'audit_record_005', 'audit_record_004'], 'identifiers': [{'kind': 'name', 'value': 'user_03'}], 'observed_state_words': ['Valid'], 'timestamps': ['25 Aug 04:03', '25 Aug 03:21', '24 Aug 16:14', '22 Aug 11:27', '20 Aug 09:42', '18 Aug 14:05', '2026-08-25T04:03:00Z', '25 Aug', '24 Aug', '22 Aug']}
```

### evidence_42

```json
{'document_type': 'console_screenshot', 'system_id': 'unknown', 'resource_ids': [], 'identifiers': [], 'observed_state_words': ['Retained reference', 'Active'], 'timestamps': ['11 Jan 2024 08:42 UTC', '10 Mar 2026 07:18 UTC', '11 Jan 2024 08:45', '14 Feb 2024 12:16', '03 Jun 2024 09:27', '22 Aug 2024 15:03', '10 Mar 2026', '22 Aug 2024', '03 Jun 2024', '14 Feb 2024', '11 Jan 2024']}
```

### evidence_46

```json
{'document_type': 'object_storage_browser', 'system_id': 'object_storage', 'resource_ids': [], 'identifiers': [{'kind': 'hash', 'value': 'e71b6d'}], 'observed_state_words': ['Standard'], 'timestamps': ['13 Feb 2026 08:00 UTC', '12 Feb 18:42', '11 Feb 14:17', '10 Feb 09:33', '11 Feb 16:05', '10 Feb 11:21', '12 Feb 10:08', '10 Feb 23:14', '12 Feb 21:56', '12 Feb 2026 18:42 UTC', '12 Feb 18:42', '12 Feb 18:39', '12 Feb 18:38']}
```

### evidence_60

```json
{'document_type': 'console_screenshot', 'system_id': 'marketing_platform', 'resource_ids': ['marketing_001'], 'identifiers': [{'kind': 'name', 'value': 'Soo-jin Park'}, {'kind': 'email', 'value': 'sj.park@naver.com'}, {'kind': 'phone', 'value': '+82 10-5837-9451'}], 'observed_state_words': ['Live', 'Yes', 'No', 'Eligible', 'Recorded'], 'timestamps': ['15 Sep 2026 23:40 UTC', '23:40', '23:38', '23:35', '23:32']}
```

