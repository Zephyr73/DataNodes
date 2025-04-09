# 🔗 Datanodes Link Extractor

This Python script automates the process of navigating Datanodes.to links, clicking through the download buttons, and extracting the final direct download URLs. It uses [Playwright](https://playwright.dev/python/) for browser automation and `tqdm` for progress tracking.
This is just a side project to learn webscraping so the code may have many flaws and it might not be as fast. Feel free to clone and modify it to make it better. I would love to see how others approach this
---

## 📦 Requirements

- Python 3.7+
- Google Chrome or Chrome Beta installed
- [Playwright](https://playwright.dev/python/) (Included in requirements.txt)
- [tqdm](https://tqdm.github.io/) (Included in requirements.txt)

## 🚀 Usage

1. Put all your links inside a file named `links.txt`, one per line.
2. Run the script:

   ```bash
   run.bat
   ```
3. This script will automatically:
   - Create a `.venv` folder
   - Install dependencies from `requirements.txt`
   - Run the webscraper
4. Open `output.txt` and copy the links to idm or jdownloader

## 🛠 Notes

- 🧭 **Browser Detection**:  
  The script uses the first Chrome installation it finds in these default Windows paths:
  - C:/Program Files/Google/Chrome Beta/Application/chrome.exe
  - C:/Program Files/Google/Chrome/Application/chrome.exe
  - C:/Program Files (x86)/Google/Chrome Beta/Application/chrome.exe
  - C:/Program Files (x86)/Google/Chrome/Application/chrome.exe
    
If you're using a different browser or Chrome is installed elsewhere, edit the `CHROME_PATHS` list in the script.

- Browser issues:
  - Due to limited testing environments, I could not see all possible errors and how to fix them.
    Most errors such as `bad gateway: 502` can be fixed by retrying the link
  - After running the whole script, the terminal will show failed links in the output logs. Put them in `links.txt` and retry the script.
  - This is just a side project to learn webscraping so the code may have many flaws and it might not be as fast. Feel free to clone and modify it to make it better. I would love to see how others approach this
