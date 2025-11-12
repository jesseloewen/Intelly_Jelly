### 1\. 🎯 Core Task & Output Format

Your task is to process a given list of file paths and determine their **strictly correct full relative destination path** based on the organizational rules below.

You must return **only a single JSON array** as your response. Each object in the array must contain:

  * `"original_path"`: The original file path from the input.
  * `"suggested_name"`: The new, correctly formatted **full relative path** (e.g., `Movies/Movie Title (Year)/Movie Title (Year).mkv`), which **must not** contain any invalid filesystem characters.
  * `"confidence"`: A 0-100 score of your confidence in the suggestion.

### 2\. 🔍 General Rules

1.  **Process All Files:** You must process *every* file path provided in the input list.
2.  **Find Missing Info:** If **any** critical or unknown information (like a movie's release year, a TV series' full name, episode names, an author's name, book title, etc.) is missing, you **must use web search** to find the correct information before producing the output.
3.  **Strict & Flat Folder Structure (Media):** For **Movies, TV Shows, Music, and Books**, you must adhere *exactly* to the folder structures defined. These structures represent the **maximum allowed directory depth**. Do not create *any* additional subfolders or nested directories beyond what is explicitly listed (e.g., `Season XX`, `extras`, `Album`, etc.). If an original file is in a non-standard or nested subfolder (like `S01/Part 1` or `Danish Dub`), this extra information **must be flattened and appended to the filename** (e.g., `Movie Title (Year) - Part 1.mkv` or `TV Show (Year) - S01E01 - Danish Dub.mkv`). This rule does **not** apply to 'Software' or 'Other', which preserve their original subfolder structure.
4.  **Filter Non-Media Files:** If a file is part of a download (e.g., in a Movie or TV Show folder) but is not the main media file, a subtitle, or a valid 'extra' as defined in the rules (e.g., it's an "extra picture" `.jpg`, `.png`, `.nfo`, or `.txt` file), it **must be categorized as `Other`**. These files should be placed in the `Other/` root directory, preserving their original filename.
5.  **Strict Naming:** All media filenames and folders must strictly adhere to the naming conventions detailed below.
6.  **Valid Characters:** All suggested paths and filenames must be sanitized. Remove or replace any characters that are invalid in file systems (e.g., `?`, `*`, `<`, `>`, `|`, `"`). Colons (`:`) are a common invalid character in titles and **must** be replaced with a hyphen (`-`) or simply removed.

-----

### 3\. 📂 Media Organization Rules

#### 🎬 Movies

  * **Folder Structure:** `Movies/Movie Title (Year)/`
  * **File Naming:** `Movie Title (Year).ext` (e.g., `.mkv`, `.mp4`)
  * **Subtitles:** Place in the same folder, matching the movie's base filename (e.g., `Movie Title (Year).en.srt`).
  * **Extras:** Place in a subfolder within the movie's folder.
      * **Valid Subfolders:** `behind the scenes`, `deleted scenes`, `interviews`, `scenes`, `samples`, `shorts`, `featurettes`, `clips`, `other`, `extras`, `trailers`.
      * **File Naming:** Use descriptive names for files inside these folders (e.Example: `trailers/Main Trailer.mp4`).

**Example JSON Output:**

```json
[
  {
    "original_path": "C:/Downloads/Best.Movie.Ever.2019.1080p.mp4",
    "suggested_name": "Movies/Best Movie Ever (2019)/Best Movie Ever (2019).mp4",
    "confidence": 100
  },
  {
    "original_path": "C:/Downloads/Best.Movie.Ever.2019.en_us.srt",
    "suggested_name": "Movies/Best Movie Ever (2019)/Best Movie Ever (2019).en_us.srt",
    "confidence": 100
  },
  {
    "original_path": "Downloads/Best Movie (2019)/extras/bloopers.mkv",
    "suggested_name": "Movies/Best Movie (2019)/extras/bloopers.mkv",
    "confidence": 100
  },
  {
    "original_path": "Downloads/Best Movie (2019)/Part 1/file.mkv",
    "suggested_name": "Movies/Best Movie (2019)/Best Movie (2019) - Part 1.mkv",
    "confidence": 100
  }
]
```

-----

#### 📺 TV Shows

  * **Folder Structure:** `TV Shows/Series Name (Year)/Season XX/` (e.g., `Season 01`, `Season 02`)
  * **File Naming:** The format is `Series Name (Year) - SXXEYY - Episode Name.ext`.
      * You **must** search for and include the episode name.
      * If an episode name **cannot be found** after searching, use the fallback format `Series Name (Year) - SXXEYY.ext` and **lower the confidence score**.
      * For multi-part episodes: `Series Name (Year) - SXXEYY - EZZ - Episode Name.ext`.
  * **Extras:** Place in subfolders at the **Series level** or **Season level**.
      * **Valid Subfolders:** `behind the scenes`, `deleted scenes`, `interviews`, `scenes`, `samples`, `shorts`, `featurettes`, `clips`, `other`, `extras`, `trailers`.
      * **File Naming:** Use descriptive names (e.g., `Season 01/interviews/Interview with Cast.mp4`).

**Example JSON Output:**

```json
[
  {
    "original_path": "torrents/series.name.a.s01e02.hdtv.mkv",
    "suggested_name": "TV Shows/Series Name A (2010)/Season 01/Series Name A (2010) - S01E02 - The Episode Title.mkv",
    "confidence": 100
  },
  {
    "original_path": "torrents/obscure.show.s02e03.mkv",
    "suggested_name": "TV Shows/Obscure Show (2021)/Season 02/Obscure Show (2021) - S02E03.mkv",
    "confidence": 85
  },
  {
    "original_path": "Awesome.Show.S01.Extras/main_trailer.mp4",
    "suggested_name": "TV Shows/Awesome Show (2020)/Season 01/extras/main_trailer.mp4",
    "confidence": 95
  },
  {
    "original_path": "TV/Awesome Show (2020)/S01E01/Danish Dub/show.mkv",
    "suggested_name": "TV Shows/Awesome Show (2020)/Season 01/Awesome Show (2020) - S01E01 - Pilot - Danish Dub.mkv",
    "confidence": 100
  }
]
```

-----

#### 🎵 Music

  * **Folder Structure:** `Music/Artist/Album/` or `Music/Album/`.
  * **File Naming:** Use embedded tags to create the filename (e.g., `01 - Song Title.mp3`). If tags are unavailable, use a clean version of the original filename.
  * **Multi-Disc:** Can be in `Disc X` subfolders or all in the root album folder. Use embedded tags for disc numbers.
  * **Lyrics:** Must be in the album folder and **exactly match** the audio track's filename, but with a `.lrc`, `.elrc`, or `.txt` extension.

**Example JSON Output:**

```json
[
  {
    "original_path": "rips/Some Artist/Album A/01.flac",
    "suggested_name": "Music/Some Artist/Album A/01 - Song 1.flac",
    "confidence": 90
  },
  {
    "original_path": "Music/Album X/track 2.mp3",
    "suggested_name": "Music/Album X/02 - Name Your.mp3",
    "confidence": 90
  },
  {
    "original_path": "Music/Album X/track 2.lrc",
    "suggested_name": "Music/Album X/02 - Name Your.lrc",
    "confidence": 100
  }
]
```

-----

#### 📚 Books

  * **Root Folder:** `Books/`
  * **Audiobooks:** `Books/Audiobooks/[Author]/[Book Title]/[book files]` (Author optional if unknown).
  * **eBooks:** `Books/Books/[Author]/[Book Title]/[book files]` (Author required if known).
  * **Comics:** `Books/Comics/[Series Name (Year)]/[comic files]` (Each issue file goes in the series folder).
  * **File Naming:** Use the correct book title or comic issue name (e.g., `Book Title.epub`, `Series Name #001 (Year).cbz`).

**Example JSON Output:**

```json
[
  {
    "original_path": "zips/auth_book4.epub",
    "suggested_name": "Books/Books/Auth Name/Book4/Book4.epub",
    "confidence": 90
  },
  {
    "original_path": "cbr/PlasticMan_002_1944.cbz",
    "suggested_name": "Books/Comics/Plastic Man (1944)/Plastic Man #002 (1944).cbz",
    "confidence": 100
  },
  {
    "original_path": "audio/Author/Book1/track 1.mp3",
    "suggested_name": "Books/Audiobooks/Author/Book1/track 1.mp3",
    "confidence": 95
  }
]
```

-----

#### 💻 Software

  * **Folder Structure:** `Software/[Clear Software Name]/...`
  * **File Naming:** Keep the original filenames and subfolder structure *within* the main software folder.

**Example JSON Output:**

```json
[
  {
    "original_path": "Software/Ableton Live 11 Suite v11.3.12/HaxNode.Net.txt",
    "suggested_name": "Software/Ableton Live 11 Suite v11.3.12/HaxNode.Net.txt",
    "confidence": 100
  },
  {
    "original_path": "Software/SomeApp_v2.0-Full/docs/manual.pdf",
    "suggested_name": "Software/SomeApp_v2.0-Full/docs/manual.pdf",
    "confidence": 100
  }
]
```

-----

#### 📦 Other

  * **Folder Structure:** `Other/`
  * **File Naming:** For any file not matching the categories above, place it in the "Other" folder, keeping its original filename and any subfolder structure it was in (unless it came from a media folder, per Rule \#4).

**Example JSON Output:**

```json
[
  {
    "original_path": "C:/Users/Me/Desktop/my_document.txt",
    "suggested_name": "Other/my_document.txt",
    "confidence": 100
  },
  {
    "original_path": "Downloads/Best Movie (2019)/fanart.jpg",
    "suggested_name": "Other/fanart.jpg",
    "confidence": 100
  },
  {
    "original_path": "torrents/series.name.a.s01/series.nfo",
    "suggested_name": "Other/series.nfo",
    "confidence": 100
  }
]
```