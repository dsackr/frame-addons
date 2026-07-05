# Contributing Scene Packs

We welcome contributions of new scene packs! Since these packs are downloaded automatically by users' integrations, we maintain high standards for image quality, display optimization, and legal compliance.

---

## ⚠️ Licensing Requirements (Critical)

All image assets contributed to this repository **must** be legally free to distribute and use. Before adding any images, verify that they meet one of the following requirements:

1. **Public Domain (Preferred):** 
   * Works where the copyright has expired (e.g., paintings from artists deceased for more than 70 years, such as Claude Monet, Vincent van Gogh).
   * Works created by the U.S. Federal Government (which are automatically public domain under US copyright law, e.g., official presidential portraits, NASA photos).
2. **Creative Commons / Open Licensing:** 
   * Openly licensed works (e.g., CC0, CC-BY, CC-BY-SA) where attribution can be verified.
3. **No Copyrighted/Proprietary Images:** 
   * Do not submit contemporary artwork, commercial photography, movie stills, or any images with restrictive licenses.

When querying Wikimedia Commons, the generator script automatically checks the file's metadata to verify it is marked as `public domain`. Any file failing this check will be skipped.

---

## How to Add a New Scene Pack

Scene packs are defined in `scripts/build_scene_pack.py` and built using Wikimedia Commons metadata.

### 1. Add the Pack Definition
Open `scripts/build_scene_pack.py` and add a new dictionary to the `PACKS` list:

```python
    {
        "id": "my_new_pack",
        "name": "My New Pack Name",
        "description": "A brief description of what this pack contains.",
        "category": "art", # Either "art" or "seasonal"
        "queries": [
            # Option A: Fuzzy Search (finds the best match for the query)
            ("Claude Monet Water Lilies painting", "Water Lilies", "Monet"),
            
            # Option B: Exact Filename (recommended when you want a specific file)
            ("File:Specific Image Filename on Commons.jpg", "Friendly Display Title", ""),
        ],
    },
```

* **Query (First value):** The search term or the exact `File:Name.jpg` from Wikimedia Commons.
* **Display Title (Second value):** The name shown to the user on the dashboard.
* **Artist Keyword (Third value):** Used for fuzzy matching to verify the artist's name in metadata. Use `""` (empty string) if you are targeting a specific filename directly.

### 2. Generate the Assets
Run the build script to download, downsize, and register the pack:

```bash
python3 scripts/build_scene_pack.py my_new_pack
```

This will:
* Query Wikimedia Commons to locate the files and check licenses.
* Download and resize the images to a max edge of 2400px (saving them under `scene_packs/my_new_pack/`).
* Update the central index `scene_packs/index.json`.

### 3. Verify & Commit
1. Check the downloaded files under `scene_packs/my_new_pack/` to ensure they are cropped correctly and look high-quality.
2. Stage and commit the changes:
   ```bash
   git add scene_packs/my_new_pack/ scene_packs/index.json scripts/build_scene_pack.py
   git commit -m "Add my_new_pack scene pack"
   git push origin main
   ```
