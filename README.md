# 💬 WhatsApp Chat Visualizer

A web application for visualizing exported WhatsApp chats with media file support.

## 🚀 Features

- **Read chats** from folders with exported WhatsApp data
- **Message visualization** in WhatsApp style (green/white bubbles)
- **Audio playback** directly in chat
- **Image and video viewing** in modal windows
- **Message search** with regex support
- **Filtering** by dates, participants, message types
- **Activity statistics** and charts
- **Pagination** for large chats

## 📋 Requirements

- Python 3.8+
- Streamlit
- Pandas
- Altair
- python-dateutil
- regex

## 🛠️ Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ruslanpolichshuk/whatsapp_viz_app.git
   cd whatsapp_viz_app
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   
   # Windows
   .venv\Scripts\activate
   
   # macOS/Linux
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install streamlit pandas altair python-dateutil regex
   ```

## 📱 Exporting chat from WhatsApp

1. Open WhatsApp on your phone
2. Go to the desired chat
3. Tap on the chat name → **Export chat**
4. Select **"Include media files"**
5. Send the file to yourself (e.g., via email)
6. Extract the ZIP archive to a folder

## 🎯 Running the application

```bash
streamlit run whatsapp_viz_app.py
```

The application will open in your browser at `http://localhost:8501`

## 📁 Usage

### 1. Selecting chat folder

- Enter the path to the folder with the exported chat in the **"Enter folder path"** field
- Or use the buttons:
  - **💡 Show common paths** - show typical paths
  - **🔍 Auto-detect in Downloads** - automatic search in Downloads folder
  - **📁 Browse for Chat Folder** - instructions for copying the path

### 2. View settings

- **Which user is 'me'** - select your name for correct message display
- **Messages per page** - number of messages per page (10-1000 or "All")
- **Page** - navigate between pages for large chats

### 3. Search and filters

- **Search text** - search message content
- **Include system messages** - show system messages
- **Participants** - filter by chat participants
- **Date range** - filter by dates

## 🎵 Supported media files

### Audio
- **Formats:** .opus, .mp3, .wav, .m4a, .ogg
- **Playback:** directly in chat with full volume control

### Video
- **Formats:** .mp4, .avi, .mov, .webm
- **Viewing:** in modal window on click

### Images
- **Formats:** .jpg, .jpeg, .png, .gif, .webp
- **Viewing:** enlarged image in modal window

### Other files
- **Download:** direct download link

## 📊 Statistics and charts

- **Total message count**
- **Number of participants**
- **Days covered**
- **Media file count**
- **Daily message chart**
- **Activity heatmap** (weekday × hour)

## ⚙️ Configuration

### Increasing file upload limit

Create `.streamlit/config.toml` file:

```toml
[server]
maxUploadSize = 2000  # 2 GB

[theme]
primaryColor = "#FF6B6B"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"
```

## 🔧 Supported export formats

### Android
```
01.01.2024, 12:34 - Name: Message
```

### iOS
```
[01.01.2024, 12:34] Name: Message
```

### New format
```
[10/1/25, 11:58:38] ~Name: Message
```

## 🐛 Troubleshooting

### Empty chat folder
- Make sure the folder contains `_chat.txt` file
- Check that the folder contains media files

### Audio not playing
- Check file format (supported: .opus, .mp3, .wav, .m4a, .ogg)
- Ensure the file is not corrupted

### Slow loading
- Use pagination (fewer messages per page)
- Disable system messages
- Apply date filters

### Encoding errors
- Ensure `_chat.txt` file is saved in UTF-8
- Check for special characters in file names

## 📝 Usage examples

### Message search
```
# Search by keywords
"important message"

# Search by date (in text)
"2024"

# Search media files
"attached:"
```

### Filtering
- **Only my messages:** select yourself in "Which user is 'me'"
- **Specific period:** set date range
- **Without system messages:** uncheck "Include system messages"

## 🤝 Contributing

1. Fork the repository
2. Create a branch for new feature
3. Make changes
4. Create a Pull Request

## 📄 License

MIT License

## 🆘 Support

If you encounter issues:

1. Check the [troubleshooting section](#-troubleshooting)
2. Create an Issue in the repository
3. Attach an example of exported chat (without personal data)

---

**Version:** 0.1  
**Last updated:** 2024
