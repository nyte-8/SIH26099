# 🎯 Material Master - Beginner's Guide

**For people who just want to use it without technical details!**

---

## What Is This?

This tool helps you **standardize material names** across your organization.

**Problem:** Different people describe the same material differently
- CPSE_A says: "Stainless Steel Pipe 50mm"
- CPSE_B says: "SS Pipe 2 inch"
- Are they the same? Yes! But a computer can't tell.

**Solution:** This tool matches them and assigns a **standard national code** like `PP-SS-050-0001`

Now everyone uses the same code. Easy!

---

## Getting Started (2 minutes)

### Step 1: Start the System

Ask your IT person to run:
```bash
python app.py
```

You'll see something like:
```
 * Running on http://127.0.0.1:5000
```

### Step 2: Open Your Browser

Go to: `http://127.0.0.1:5000`

You'll see a page with **3 tabs** at the top.

---

## What Are the 3 Tabs?

```
┌──────────────────────────────────────┐
│ 📤 Upload │ 📚 Registry │ ✅ Review  │
└──────────────────────────────────────┘
```

- **📤 Upload** — Add new materials (one at a time OR upload many at once)
- **📚 Registry** — Browse all materials that exist
- **✅ Review** — Approve materials that need a human check

Let's learn each one.

---

## Tab 1: Upload Materials

### Single Material Entry

You have **one material** to add? Use this.

1. **Click Tab 1** (should already be selected)

2. **Fill in 4 boxes:**
   - **CPSE ID:** Your organization code (e.g., "CPSE_A" or "BHEL")
   - **Material Code:** Your internal code (e.g., "MAT-1001" or "PIPE-50")
   - **Description:** What it is (e.g., "Stainless Steel Pipe 50mm")
   - **Specification:** More details (e.g., "Schedule 40, no coating")

3. **Click "Standardize"**

4. **Wait for result** (2-5 seconds)

You'll see:
```
✓ Successfully standardized!

National Code: PP-SS-050-0001
Status: CONFIRMED (High confidence match)
Confidence: 95%
```

**Done!** Your material now has a standard code.

---

### Bulk Upload (Many Materials at Once)

You have **50 materials** to upload? Use this.

1. **Click the radio button** next to "Bulk CSV Upload"

2. **Prepare your file** with these columns:
   ```
   CPSE_ID, Material_Code, Description, Specification
   ```

   **Example file contents:**
   ```csv
   CPSE_A,MAT_1001,Stainless Steel Pipe 50mm,Schedule 40
   CPSE_A,MAT_1002,Carbon Steel Pipe 25mm,Schedule 40
   CPSE_B,MAT_2005,SS Pipe 50mm bore,Same as CPSE_A MAT_1001
   CPSE_B,MAT_2010,Brass Pipe 100mm,Special alloy
   ```

   **Important:**
   - Save as `.csv` file (not Excel)
   - First row should be column names
   - Required columns: CPSE_ID, Material_Code, Description, Specification
   - Column order doesn't matter

3. **Click "Choose File"** and select your CSV

4. **Click "Upload & Process"**

5. **Wait for results** (shows progress)

You'll see:
```
Upload Results
━━━━━━━━━━━━━━━━━━━
Total rows: 4
Successfully processed: 4
Errors: 0

Details:
Row 1: ✓ Success → PP-SS-050-0001 (Confirmed)
Row 2: ✓ Success → PP-CS-025-0001 (Confirmed)
Row 3: ✓ Success → PP-SS-050-0001 (Already exists)
Row 4: ⏳ Pending → PP-BR-100-0001 (Needs review)
```

**That's it!** All 4 materials processed.

---

## Tab 2: Registry (Browse All Materials)

Want to see what materials exist? Use this.

### What You See

1. **Click Tab 2** 

2. **A list appears:**
   ```
   PP-SS-050-0001 (Pipe - Stainless Steel, 50mm)
   ×3 records

   PP-CS-025-0001 (Pipe - Carbon Steel, 25mm)
   ×2 records

   VV-BR-100-0001 (Valve - Brass, 100mm)
   ×1 record (🔴 PENDING)
   ```

What do these mean?
- `PP-SS-050-0001` — The national code
- `(Pipe - Stainless Steel, 50mm)` — What material it is
- `×3 records` — 3 different CPSEs submitted this same material
- `🔴 PENDING` — Needs human approval (see Tab 3)

### Expand to See Details

Click any material row to expand:

```
┌─────────────────────────────────────┐
│ PP-SS-050-0001 ▼                    │
├─────────────────────────────────────┤
│ Category: Pipe                      │
│ Description: Stainless Steel Pipe   │
│ Standard 50mm bore                  │
│                                     │
│ Source entries:                     │
│  CPSE_A · MAT_1001    95% Confirmed │
│  CPSE_B · MAT_2005    92% Confirmed │
│  CPSE_C · MAT_3010    78% Pending   │
└─────────────────────────────────────┘
```

This shows:
- **CPSE_A · MAT_1001:** CPSE_A called it "MAT_1001", 95% match confidence
- **Status:** Confirmed = Approved and in the registry
- **Status:** Pending = Still needs human review

**Why would it be Pending?** — The system is 75% sure it's the same material, but not 100% sure. A human should double-check.

---

## Tab 3: Review Materials (For Managers/Admins)

**This is the "approval" tab.** If something needs human approval, it shows here.

### When Do Items Appear Here?

When the system finds a match that's between **70-85% confident**.

Example:
- System sees: "Stainless Steel Pipe 50mm" and "SS Pipe 50 bore"
- Similarity: 75% (good match, but wording differs)
- Decision: "Not sure enough, ask a human"
- Result: Item appears in Tab 3

### What to Do

1. **Click Tab 3**

2. **See a list of items needing approval:**
   ```
   CPSE_C · MAT_3010 → Merge with PP-SS-050-0001?
   Confidence: 78%
   
   Attributes match:
   ✓ Diameter: 50mm = 50mm (perfect)
   ✓ Material: SS = Stainless Steel (good)
   ✗ Schedule: Unknown vs Schedule 40 (can't confirm)
   
   [✓ Approve Merge]  [✗ Request New Code]
   ```

### Make a Decision

**✓ Click "Approve Merge"** if:
- Attributes look the same
- It's obviously the same material
- The name differences are just wording

Result: Material is merged with PP-SS-050-0001, status changes to CONFIRMED

**✗ Click "Request New Code"** if:
- Attributes are different
- It's actually a different material
- You're not sure

Result: Material gets a new unique code

---

## Real-World Example

Let's walk through a complete scenario.

### Day 1: CPSE_A Uploads

**Tab 1 → Single Entry**
```
CPSE ID: CPSE_A
Material Code: MAT_1001
Description: Stainless Steel Pipe 50mm Diameter
Specification: SS schedule 40, no coating
```
✓ Result: Gets code `PP-SS-050-0001` (CONFIRMED)

### Day 2: CPSE_B Uploads

**Tab 1 → Single Entry**
```
CPSE ID: CPSE_B
Material Code: MAT_2005
Description: SS Pipe 50mm Schedule 40
Specification: Stainless Steel
```
✓ Result: Gets same code `PP-SS-050-0001` (CONFIRMED)

Why? The system recognized this is the same pipe CPSE_A uploaded, even though the wording is different.

### Day 3: CPSE_C Uploads

**Tab 1 → Single Entry**
```
CPSE ID: CPSE_C
Material Code: MAT_3010
Description: Stainless Steel Pipe 50mm but galvanized
Specification: SS with zinc coating
```
⏳ Result: Gets code `PP-SS-050-0001` BUT marked as PENDING (77% match)

Why? System sees "50mm pipe, stainless steel" and thinks it might be the same as the existing code. But "galvanized" is different (coating), so it's not 100% sure.

### Day 4: Manager Reviews

**Tab 3 → Admin Review**

Sees:
```
CPSE_C · MAT_3010 → Merge with PP-SS-050-0001?
Confidence: 77%
Attributes: diameter ✓, material ✓, coating ✗ (galvanized vs none)
```

Manager clicks **"Request New Code"** because galvanized coating makes it different.

✓ Result: CPSE_C's material gets a NEW code like `PP-SS-050-0002` (galvanized variant)

### Tab 2: Registry Now Shows

```
PP-SS-050-0001 (Pipe - Stainless Steel, 50mm)
×2 records
  CPSE_A · MAT_1001    95% Confirmed
  CPSE_B · MAT_2005    92% Confirmed

PP-SS-050-0002 (Pipe - Stainless Steel Galvanized, 50mm)
×1 record
  CPSE_C · MAT_3010    77% Confirmed (was Pending, now approved)
```

**Perfect!** Now the registry correctly shows:
- Two similar materials (the standard pipe and the galvanized pipe)
- Which CPSE uses which
- Everyone knows there's a difference

---

## Common Questions

### "My material got a status 'Pending Review'. What does that mean?"

It means the system thinks it might match an existing material, but it's not 100% sure (70-85% confident). A manager needs to check Tab 3 and approve or reject it. Don't worry, it will get a final code either way.

### "I uploaded a material and it has the SAME code as another CPSE's material. Does that mean they're the same?"

Yes! The system matched them. Two different CPSEs submitted what the system believes is the same material. That's the whole point — now you can reuse the same code.

### "Can I change the code once it's assigned?"

The system automatically generates codes in the format `CATEGORY-MATERIAL-DIM-SERIAL` (like `PP-SS-050-0001`). You can't manually edit these codes (they're automated), but managers can request a new code via Tab 3 Review.

### "What if I made a mistake in the Description?"

If you uploaded with the wrong description, currently you'd need to re-upload with the correct details. A manager can then review both entries in Tab 3 and approve the correct one. (Future versions may add an "edit" feature.)

### "How long does processing take?"

Usually **2-5 seconds** for each material. For bulk CSV uploads with 100+ materials, it may take a minute or two.

### "What if the system is slow or broken?"

Ask your IT person to check:
1. Is the Flask server still running? (Should see "Running on http://127.0.0.1:5000")
2. Are there any error messages in the terminal?
3. Try refreshing your browser (Ctrl+R)

---

## The Code Format Explained (Simple Version)

Codes look like: `PP-SS-050-0001`

Breaking it down:
- **PP** = Pipe (category)
- **SS** = Stainless Steel (material type)
- **050** = 50mm (size)
- **0001** = 1st pipe in this size/material combo

That's it! The code tells you what the material is just by looking at it. No mystery.

Other examples:
- `VV-BR-100-0002` = Valve, Brass, 100mm, 2nd one
- `FT-STL-006-0001` = Fastener, Steel, 6mm, 1st one
- `EC-CU-025-0003` = Electrical Cable, Copper, 25mm, 3rd one

---

## Troubleshooting for Beginners

### Problem: "I clicked Upload but nothing happened"

**Try this:**
1. Check if you filled in all 4 boxes (CPSE ID, Material Code, Description, Specification)
2. Look at your browser's "Console" (press F12, click "Console" tab)
3. Are there any red error messages?
4. Try clicking the button again

### Problem: "CSV upload says 'Error: Invalid file format'"

**Check:**
1. Did you save it as `.csv` (not `.xlsx` or `.xls`)?
2. Does the first row have column names: `CPSE_ID, Material_Code, Description, Specification`?
3. Are there any weird characters in the data?
4. Try opening the CSV in Notepad (not Excel) to check formatting

### Problem: "I can't see Tab 3 (Review tab)"

**Most likely:** There are no pending materials yet!

Tab 3 is empty until someone uploads a material that's 70-85% similar to an existing one. Once you have pending items, Tab 3 will show them.

### Problem: "The website shows a blank page"

**Try:**
1. Refresh (Ctrl+R or Cmd+R)
2. Close the browser tab and open a new one
3. Go to `http://127.0.0.1:5000` again
4. Check that Flask is still running (ask IT person)

### Problem: "I uploaded materials but they're not showing in Tab 2"

**Give it a moment:** Processing takes 2-5 seconds per material. After uploading, click Tab 2 and refresh (or wait a few seconds and reload).

---

## Tips for Best Results

✅ **Good descriptions:**
- "Stainless Steel Pipe 50mm Schedule 40"
- "Brass Gate Valve 100mm Class 300"
- "6mm Bolt Grade 8.8 Zinc Coated"

❌ **Vague descriptions:**
- "Pipe"
- "Thing"
- "Metal part 123"

✅ **Good specifications:**
- "Stainless Steel 304, no coating"
- "Copper UNS C12200, annealed"

❌ **Vague specifications:**
- "Standard"
- "Normal"
- "Same as usual"

**Why?** Better descriptions help the system match materials more accurately.

---

## Visual Quick Reference

### Upload Flow
```
Tab 1: Upload
  │
  ├─ Single Entry Mode
  │  ├─ Fill 4 boxes
  │  ├─ Click Standardize
  │  └─ See code + status
  │
  └─ Bulk CSV Mode
     ├─ Prepare CSV file
     ├─ Select file
     ├─ Click Upload
     └─ See results for each row
```

### Browse Flow
```
Tab 2: Registry
  │
  ├─ See all material codes
  ├─ See how many CPSEs use each
  └─ Click to expand
     ├─ See category
     ├─ See description
     └─ See all CPSE entries (with confidence %)
```

### Review Flow
```
Tab 3: Review
  │
  ├─ See pending materials (only if 70-85% confident)
  └─ For each:
     ├─ See what it would merge with
     ├─ See attribute match/conflict
     ├─ Click "Approve" OR "Request New Code"
     └─ Material gets final status
```

---

## Next Steps

### You're ready to use it! ✅

1. Ask your IT person to start the Flask server
2. Open the website in your browser
3. Start with Tab 1 to add a material
4. Check Tab 2 to see your material in the registry
5. (Optional) Help review materials in Tab 3

### You need more detail?

- If you're **deploying** or **testing**: Read [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- If you want **technical explanations**: Read [TECHNICAL_DEEP_DIVE.md](TECHNICAL_DEEP_DIVE.md)
- If you're **lost**: Read [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)

---

## That's It!

You now know how to:
- ✅ Add materials (single or bulk)
- ✅ Browse the registry
- ✅ Approve or reject pending materials

**Happy standardizing!** 🎯

---

**Questions?** Ask your manager or IT team!  
**Version:** 1.0 - Beginner Friendly  
**Last Updated:** 2026-08-30
