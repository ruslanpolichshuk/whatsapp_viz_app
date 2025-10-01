"""
WhatsApp Dialog Visualizer — Streamlit App
-------------------------------------------------
Features (v0.1):
- Upload a single exported WhatsApp chat (.txt) — with or without media
- Robust parser for Android/iOS export formats (EN/RU friendly)
- Interactive filters: by date range, participants, and full‑text search
- Quick stats: total messages, per‑person counts, media count
- Visualizations:
    • Messages over time (daily)
    • Activity heatmap (weekday × hour)
- Message explorer table with filters

How to run locally:
1) Create a virtual environment and install deps:
   python -m venv .venv && .venv/Scripts/activate  (Windows)
   # or: source .venv/bin/activate  (macOS/Linux)
   pip install -U streamlit pandas numpy python-dateutil altair regex

2) Start the app:
   streamlit run whatsapp_viz_app.py

3) Export a chat from WhatsApp as .txt (Settings → Chats → Export chat). 
   Drag the .txt file into the uploader. If you exported "with media", 
   you can also zip the media folder and upload (optional) — for now we only count media placeholders in text.

Notes:
- Timezone is not modified; dates are parsed as-is from the export.
- Supported timestamp formats include (examples):
  • "01.01.2024, 12:34 - Name: message"  (Android)
  • "[01.01.2024, 12:34] Name: message"  (iOS)
  • Variants with AM/PM and locales (en/ru). The parser tries multiple patterns.

Planned next steps:
- Map media filenames to messages using the exported media folder
- Per-user word stats, emoji stats, and reply chains
- Conversation graph (who replies to whom)
"""

from __future__ import annotations

import base64
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import altair as alt
import numpy as np
import pandas as pd
import regex as rx
from dateutil import parser as dtparser
import streamlit as st
import streamlit.components.v1 as components

# ==========================
# Utility Functions
# ==========================

def get_file_base64(file_path: str) -> str:
    """Convert file to base64 string for embedding in HTML"""
    try:
        with open(file_path, 'rb') as f:
            data = f.read()
            # Check if file is not empty
            if len(data) == 0:
                st.warning(f"File {file_path} is empty")
                return ""
            return base64.b64encode(data).decode('utf-8')
    except Exception as e:
        st.error(f"Error reading file {file_path}: {str(e)}")
        return ""

# ==========================
# Parsing Logic
# ==========================
# WhatsApp exports have two common shapes:
#  A) Android:  "DD.MM.YYYY, HH:MM - Name: Message"
#  B) iOS:      "[DD.MM.YYYY, HH:MM] Name: Message"  or "DD/MM/YY, HH:MM - Name: Message"
#  Plus 12h/AM-PM variants and different separators.
#  Multiline messages: subsequent lines do not start with a timestamp prefix.

# Precompile multiple timestamp regexes (EN/RU tolerant)
# We capture: datetime string, then user, then message

# New format: [10/1/25, 11:58:38] ~Gulmira: message
# Note: Handle invisible Unicode characters like \u200e
NEW_BRACKET_RE = rx.compile(
    r"^[\u200e]*\[(?P<dt>\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}:\d{2})\]\s+(?P<user>[^:]+):\s+(?P<msg>.*)$"
)

# Media attachment format: [10/1/25, 12:02:23] ~Gulmira: ‎<attached: filename>
# Note: Handle invisible Unicode characters like \u200e
MEDIA_ATTACHMENT_RE = rx.compile(
    r"^[\u200e]*\[(?P<dt>\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}:\d{2})\]\s+(?P<user>[^:]+):\s+[\u200e]*<attached:\s+(?P<filename>[^>]+)>$"
)

# Original Android format: "01.01.2024, 12:34 - Name: message"
ANDROID_RE = rx.compile(
    r"^(?P<dt>\d{1,2}[./]\d{1,2}[./]\d{2,4},?\s+\d{1,2}:\d{2}(?:\s*[APap][Mm])?)\s+-\s+(?P<user>[^:]+):\s+(?P<msg>.*)$"
)

# Original iOS bracket format: "[01.01.2024, 12:34] Name: message"
IOS_BRACKET_RE = rx.compile(
    r"^\[(?P<dt>\d{1,2}[.//]\d{1,2}[.//]\d{2,4},?\s+\d{1,2}:\d{2}(?:\s*[APap][Mm])?)\]\s+(?P<user>[^:]+):\s+(?P<msg>.*)$"
)

# Generic format fallback
GENERIC_RE = rx.compile(
    r"^(?P<dt>\d{1,2}[.//]\d{1,2}[.//]\d{2,4},?\s+\d{1,2}:\d{2}(?:\s*[APap][Mm])?)\s+-\s+(?P<user>[^:]+):\s+(?P<msg>.*)$"
)

# System messages
SYSTEM_LINE_RE = rx.compile(
    # Lines like: "01.01.2024, 12:34 - Messages to this group are now secured with end-to-end encryption."
    r"^(?P<dt>\d{1,2}[.//]\d{1,2}[.//]\d{2,4},?\s+\d{1,2}:\d{2}(?:\s*[APap][Mm])?)\s+-\s+(?P<msg>.+)$"
)

MEDIA_MARKERS = {
    "<Media omitted>",  # EN Android/iOS
    "<Медиафайл опущен>",  # RU
    "<Arquivo de mídia omitido>",  # PT
    "<Archivo omitido>",  # ES
    "<attached:",  # New format media attachments
}

@dataclass
class ChatLine:
    dt_raw: str
    user: Optional[str]
    text: str
    is_system: bool


def parse_datetime(s: str) -> Optional[pd.Timestamp]:
    # Try month-first parsing primarily for MM/DD/YY format; fallback to day-first
    for dayfirst in (False, True):
        try:
            return pd.to_datetime(dtparser.parse(s, dayfirst=dayfirst))
        except Exception:
            pass
    return None


def iter_lines(text: str) -> Iterable[str]:
    # Normalize Windows newlines
    for line in text.splitlines():
        yield line.strip("\ufeff\ufeff\ufeff\n\r ")


def parse_whatsapp_export(txt: str) -> List[ChatLine]:
    rows: List[ChatLine] = []
    current: Optional[ChatLine] = None

    for raw in iter_lines(txt):
        if not raw:
            # Empty line — append to current message as newline
            if current is not None:
                current.text += "\n"
            continue

        # Try new format first, then fall back to original formats
        m = (NEW_BRACKET_RE.match(raw) or 
             MEDIA_ATTACHMENT_RE.match(raw) or 
             ANDROID_RE.match(raw) or 
             IOS_BRACKET_RE.match(raw) or 
             GENERIC_RE.match(raw))
        
        if m:
            # Commit previous
            if current is not None:
                rows.append(current)
            dt_str = m.group("dt")
            user = m.group("user").strip()
            
            # Handle media attachments
            if "filename" in m.groupdict() and m.group("filename"):
                msg = f"<attached: {m.group('filename')}>"
            else:
                msg = m.group("msg")
                
            current = ChatLine(dt_raw=dt_str, user=user, text=msg, is_system=False)
            continue

        # System message line (no user)
        m2 = SYSTEM_LINE_RE.match(raw)
        if m2:
            if current is not None:
                rows.append(current)
            dt_str = m2.group("dt")
            msg = m2.group("msg")
            current = ChatLine(dt_raw=dt_str, user=None, text=msg, is_system=True)
            continue

        # Continuation of previous message
        if current is None:
            # Orphan line without header — treat as system without date
            current = ChatLine(dt_raw="", user=None, text=raw, is_system=True)
        else:
            current.text += ("\n" if current.text else "") + raw

    if current is not None:
        rows.append(current)

    return rows


# ==========================
# DataFrame Utilities
# ==========================

def to_dataframe(lines: List[ChatLine]) -> pd.DataFrame:
    df = pd.DataFrame([
        {
            "dt_raw": ln.dt_raw,
            "user": (ln.user or "—system—").strip(),
            "text": ln.text or "",
            "is_system": ln.is_system,
        }
        for ln in lines
    ])

    # Parse timestamps
    df["timestamp"] = df["dt_raw"].apply(parse_datetime)
    # Some orphan/system lines may have None — we'll handle this properly

    # Basic derived fields - only for valid timestamps
    df["date"] = df["timestamp"].apply(lambda x: x.date() if pd.notna(x) else None)
    df["hour"] = df["timestamp"].apply(lambda x: x.hour if pd.notna(x) else None)
    df["weekday"] = df["timestamp"].apply(lambda x: x.day_name() if pd.notna(x) else None)

    # Media flag (heuristic)
    df["is_media"] = df["text"].apply(lambda t: any(mark in t for mark in MEDIA_MARKERS))

    return df


def filter_df(
    df: pd.DataFrame,
    users: Optional[List[str]] = None,
    date_range: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None,
    query: str = "",
    include_system: bool = False,
) -> pd.DataFrame:
    out = df.copy()
    if not include_system:
        out = out[~out["is_system"]]
    if users:
        out = out[out["user"].isin(users)]
    if date_range and all(date_range):
        start, end = date_range
        out = out[(out["timestamp"] >= start) & (out["timestamp"] <= end)]
    if query:
        # Case-insensitive contains, supports Cyrillic
        pat = rx.compile(rx.escape(query), flags=rx.IGNORECASE)
        out = out[out["text"].apply(lambda s: bool(pat.search(s)))]
    return out


# ==========================
# Streamlit App
# ==========================

st.set_page_config(page_title="WhatsApp Dialog Visualizer", layout="wide")
st.title("💬 WhatsApp Dialog Visualizer")
st.caption("Select a folder containing WhatsApp chat export (_chat.txt and media files).")

with st.sidebar:
    st.header("1) Select Chat Folder")
    
    # Folder selection using text input
    folder_path = st.text_input(
        "Enter folder path:",
        placeholder="C:\\Users\\Username\\Downloads\\WhatsApp Chat - Самат🦅",
        help="Enter the full path to the folder containing _chat.txt and media files"
    )
    
    # Quick path suggestions
    if st.button("💡 Show common paths"):
        st.markdown("**Common WhatsApp export locations:**")
        st.code("C:\\Users\\Username\\Downloads\\WhatsApp Chat - [Name]")
        st.code("C:\\Users\\Username\\Documents\\WhatsApp Chat - [Name]")
        st.code("C:\\Users\\Username\\Desktop\\WhatsApp Chat - [Name]")
        st.markdown("Replace `[Name]` with the actual chat name.")
    
    # Alternative: Browse button simulation
    st.markdown("**Or browse for folder:**")
    if st.button("📁 Browse for Chat Folder"):
        st.info("💡 Tip: Copy the folder path from Windows Explorer and paste it above.")
        st.markdown("**How to get folder path:**")
        st.markdown("1. Open Windows Explorer")
        st.markdown("2. Navigate to your WhatsApp chat folder")
        st.markdown("3. Click in the address bar to select the full path")
        st.markdown("4. Copy (Ctrl+C) and paste (Ctrl+V) above")
    
    # Auto-detect button
    if st.button("🔍 Auto-detect in Downloads"):
        downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
        if os.path.exists(downloads_path):
            # Look for WhatsApp chat folders
            whatsapp_folders = []
            try:
                for item in os.listdir(downloads_path):
                    if item.startswith("WhatsApp Chat - "):
                        full_path = os.path.join(downloads_path, item)
                        if os.path.isdir(full_path):
                            whatsapp_folders.append(full_path)
            except:
                pass
            
            if whatsapp_folders:
                st.success(f"Found {len(whatsapp_folders)} WhatsApp chat folder(s):")
                for folder in whatsapp_folders[:5]:  # Show max 5
                    st.code(folder)
                st.info("Copy one of these paths and paste above.")
            else:
                st.warning("No WhatsApp chat folders found in Downloads.")
        else:
            st.error("Downloads folder not found.")
    
    st.markdown("_Select a folder containing WhatsApp chat export (_chat.txt and media files)._")
    
    # Show loaded chats
    if 'loaded_chats' not in st.session_state:
        st.session_state.loaded_chats = []
    
    if folder_path and os.path.exists(folder_path):
        # Add new chat to the list
        chat_name = os.path.basename(folder_path)
        # Clean up chat name
        if chat_name.startswith("WhatsApp Chat - "):
            chat_name = chat_name[16:]  # Remove "WhatsApp Chat - "
        if chat_name.endswith("[1]"):
            chat_name = chat_name[:-3]  # Remove "[1]"
        
        if chat_name not in st.session_state.loaded_chats:
            st.session_state.loaded_chats.append(chat_name)
    
    # Chat selector will be at the bottom

# Add chat selector at the bottom of sidebar
if st.session_state.loaded_chats:
    st.markdown("---")
    st.header("📁 Select Chat")
    
    # Initialize selected chat
    if 'selected_chat' not in st.session_state:
        st.session_state.selected_chat = st.session_state.loaded_chats[0]
    
    # Chat selector
    selected_chat = st.selectbox(
        "Choose chat to view:",
        options=st.session_state.loaded_chats,
        index=st.session_state.loaded_chats.index(st.session_state.selected_chat) if st.session_state.selected_chat in st.session_state.loaded_chats else 0,
        key="chat_selector"
    )
    
    # Update selected chat
    if selected_chat != st.session_state.selected_chat:
        st.session_state.selected_chat = selected_chat
        st.rerun()
    
    # Clear all chats button
    if st.button("🗑️ Clear All Chats"):
        st.session_state.loaded_chats = []
        st.session_state.selected_chat = None
        # Clear all chat cache keys
        keys_to_remove = [key for key in st.session_state.keys() if key.startswith('chat_')]
        for key in keys_to_remove:
            del st.session_state[key]
        st.rerun()

if not folder_path or not os.path.exists(folder_path):
    st.info("Enter a valid folder path containing WhatsApp chat export to begin.")
    st.stop()

# Process the selected folder
if st.session_state.get('selected_chat'):
    # Find the folder that matches the selected chat
    current_folder = None
    for chat_name in st.session_state.loaded_chats:
        if chat_name == st.session_state.selected_chat:
            # Try to find folder with this name
            possible_paths = [
                os.path.join(os.getcwd(), chat_name),
                os.path.join(os.getcwd(), f"WhatsApp Chat - {chat_name}"),
                os.path.join(os.getcwd(), f"WhatsApp Chat - {chat_name}[1]"),
                folder_path  # Current folder path
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    current_folder = path
                    break
            break
    
    if not current_folder:
        st.error(f"Could not find folder for chat: {st.session_state.selected_chat}")
        st.stop()
else:
    # Use current folder path
    current_folder = folder_path

# Read chat data from folder
try:
    # Use the selected folder directly
    extracted_dir = current_folder
    
    # Check if we need to re-read (if chat changed)
    chat_cache_key = f"chat_{st.session_state.get('selected_chat', 'default')}"
    if chat_cache_key not in st.session_state:
        st.session_state[chat_cache_key] = {}
    
    # Read if not already cached
    if 'raw_txt' not in st.session_state[chat_cache_key]:
        # Look for _chat.txt in the folder
        chat_files = [f for f in os.listdir(extracted_dir) if f.endswith('_chat.txt')]
        
        if not chat_files:
            st.error("No _chat.txt file found in the folder. Please ensure the folder contains the WhatsApp chat export.")
            st.stop()
        
        # Use the first _chat.txt file found
        chat_file = chat_files[0]
        chat_file_path = os.path.join(extracted_dir, chat_file)
        
        with open(chat_file_path, 'r', encoding='utf-8') as f:
            raw_txt = f.read()
        
        # Count media files for info
        media_files = [f for f in os.listdir(extracted_dir) if not f.endswith('_chat.txt')]
        
        # Cache the data
        st.session_state[chat_cache_key] = {
            'raw_txt': raw_txt,
            'media_files': media_files,
            'media_dir': extracted_dir
        }
        
        st.sidebar.success(f"Loaded from: {os.path.basename(extracted_dir)}/")
    else:
        # Use cached data
        raw_txt = st.session_state[chat_cache_key]['raw_txt']
        media_files = st.session_state[chat_cache_key]['media_files']
        st.sidebar.info(f"Using cached data from: {os.path.basename(extracted_dir)}/")
    
    st.session_state.media_dir = extracted_dir
    
    st.sidebar.info(f"Found {len(media_files)} media files in the folder.")
        
except Exception as e:
    st.error(f"Error reading folder: {str(e)}")
    st.stop()
lines = parse_whatsapp_export(raw_txt)

df = to_dataframe(lines)

if df.empty:
    st.error("Could not parse any messages. Please verify the export format.")
    st.stop()

# Sidebar filters
with st.sidebar:
    st.header("2) Filters")
    participants = sorted([u for u in df["user"].unique().tolist() if u != "—system—"]) or ["—"]
    sel_users = st.multiselect("Participants", options=participants, default=participants)

    min_ts = df["timestamp"].dropna().min()
    max_ts = df["timestamp"].dropna().max()
    
    # Handle date range input with proper None handling
    if pd.notna(min_ts) and pd.notna(max_ts):
        default_start = min_ts.date()
        default_end = max_ts.date()
    else:
        default_start = None
        default_end = None
    
    dr = st.date_input(
        "Date range",
        value=(default_start, default_end) if default_start and default_end else None,
    )
    # Convert date to Timestamps covering full days
    date_range: Optional[Tuple[pd.Timestamp, pd.Timestamp]] = None
    if isinstance(dr, (list, tuple)) and len(dr) == 2 and all(dr):
        start = pd.Timestamp(dr[0])
        end = pd.Timestamp(dr[1]) + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
        date_range = (start, end)

    # Search and filters will be moved above chat

# Apply filters (using values from above chat)
# Initialize search and system variables
q = ""
show_system = False
fdf = filter_df(df, users=sel_users, date_range=date_range, query=q, include_system=show_system)

# KPI row
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Total messages", int(len(fdf)))
with c2:
    st.metric("Participants", int(fdf["user"].nunique()))
with c3:
    st.metric("Days covered", int(fdf["date"].nunique()))
with c4:
    st.metric("Media (heuristic)", int(fdf["is_media"].sum()))

st.divider()

# Charts
st.subheader("Messages over time (daily)")
# Ensure timestamp column is properly converted to datetime and filter valid timestamps
valid_timestamps = fdf.dropna(subset=["timestamp"]).copy()
if not valid_timestamps.empty:
    valid_timestamps["timestamp"] = pd.to_datetime(valid_timestamps["timestamp"])
    by_day = (
        valid_timestamps.assign(day=lambda d: d["timestamp"].dt.floor("D"))
        .groupby("day").size().reset_index(name="messages")
    )
else:
    by_day = pd.DataFrame(columns=["day", "messages"])

if not by_day.empty:
    chart = (
        alt.Chart(by_day)
        .mark_bar()
        .encode(x=alt.X("day:T", title="Date"), y=alt.Y("messages:Q", title="Messages"))
        .properties(height=200)
        .interactive()
    )
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("No dated messages available for the selected filters.")

st.subheader("Activity heatmap (weekday × hour)")
# Ensure timestamp column is properly converted to datetime and filter valid timestamps
valid_timestamps_heat = fdf.dropna(subset=["timestamp"]).copy()
if not valid_timestamps_heat.empty:
    valid_timestamps_heat["timestamp"] = pd.to_datetime(valid_timestamps_heat["timestamp"])
    heat = valid_timestamps_heat.assign(
        Weekday=lambda d: d["timestamp"].dt.day_name(),
        Hour=lambda d: d["timestamp"].dt.hour,
    )
else:
    heat = pd.DataFrame(columns=["timestamp", "Weekday", "Hour"])
if not heat.empty:
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    heat_counts = heat.groupby(["Weekday", "Hour"]).size().reset_index(name="count")
    heat_chart = (
        alt.Chart(heat_counts)
        .mark_rect()
        .encode(
            x=alt.X("Hour:O", title="Hour"),
            y=alt.Y("Weekday:O", sort=order, title="Weekday"),
            tooltip=["Weekday", "Hour", "count"],
            color=alt.Color("count:Q", title="Messages"),
        )
        .properties(height=220)
    )
    st.altair_chart(heat_chart, use_container_width=True)
else:
    st.info("Not enough data for a heatmap with current filters.")

st.divider()

# Chat Visualization
# Extract chat title from folder path
chat_title = "Chat"
if current_folder:
    filename = os.path.basename(current_folder)
    # Remove "WhatsApp Chat - " prefix and ".zip" suffix
    if filename.startswith("WhatsApp Chat - "):
        chat_title = filename[16:]  # Remove "WhatsApp Chat - "
    if chat_title.endswith(".zip"):
        chat_title = chat_title[:-4]  # Remove ".zip"
    if chat_title.endswith("[1]"):
        chat_title = chat_title[:-3]  # Remove "[1]"

st.subheader(f"💬 {chat_title}")

# Search and filters above chat (second row)
col1, col2, col3, col4 = st.columns([2, 1, 1, 1])

with col1:
    q = st.text_input("Search text (regex-safe, case-insensitive contains)", key="search_above_chat")

with col2:
    show_system = st.checkbox("Include system messages", value=False, key="system_above_chat")

with col3:
    st.write("")  # Spacer

with col4:
    st.write("")  # Spacer

# Chat View Settings above chat
participants = sorted([u for u in df["user"].unique().tolist() if u != "—system—"]) or ["—"]
if participants and participants != ["—"]:
    me_user = participants[0]  # Default to first participant
else:
    me_user = None

# Re-apply filters with values from above chat
q = st.session_state.get('search_above_chat', '')
show_system = st.session_state.get('system_above_chat', False)
fdf = filter_df(df, users=sel_users, date_range=date_range, query=q, include_system=show_system)

# Create a chat-like visualization
if not fdf.empty:
    # Sort messages by timestamp (oldest first for chat view)
    chat_messages = fdf.sort_values("timestamp", ascending=True).reset_index(drop=True)
    
    # Show message count
    total_messages = len(chat_messages)
    st.info(f"Showing {total_messages} messages")
    
    # Chat View Settings in one line (without fullscreen)
    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
    
    with col1:
        if participants and participants != ["—"]:
            me_user = st.selectbox("Which user is 'me'", options=participants, index=0, key="me_user_selector")
        else:
            me_user = None
    
    with col2:
        messages_per_page_options = [10, 20, 50, 100, 200, 500, 1000, "All"]
        messages_per_page_choice = st.selectbox(
            "Messages per page:",
            options=messages_per_page_options,
            index=3,  # Default to 100
            key="messages_per_page"
        )
    
    with col3:
        # Convert "All" to total messages count
        if messages_per_page_choice == "All":
            messages_per_page = total_messages
        else:
            messages_per_page = messages_per_page_choice
        
        # Add pagination for large chats
        if total_messages > messages_per_page:
            total_pages = (total_messages + messages_per_page - 1) // messages_per_page
            page = st.selectbox("Page", range(1, total_pages + 1), index=total_pages - 1, key="page_selector")
            
            # Calculate message range for current page
            start_idx = (page - 1) * messages_per_page
            end_idx = min(start_idx + messages_per_page, total_messages)
            chat_messages = chat_messages.iloc[start_idx:end_idx]
            
            st.caption(f"Showing {start_idx + 1}-{end_idx} of {total_messages}")
        else:
            st.caption(f"All {total_messages} messages")
    
    with col4:
        st.write("")  # Spacer
    
    # Create a container for the chat
    chat_container = st.container()
    
    with chat_container:
        # Normal chat mode (no fullscreen)
        chat_height = "600px"
        chat_style = f"""
        height: {chat_height}; 
        overflow-y: auto; 
        border: 1px solid #ddd; 
        border-radius: 10px; 
        padding: 10px; 
        background-color: #f8f9fa;
        margin-bottom: 20px;
        """
        
        # Create scrollable window using components.html
        chat_html = f"""
        <div style="{chat_style}">
        """
        
        # Add all messages to the HTML
        for idx, row in chat_messages.iterrows():
            # Determine if this is a system message
            if row["is_system"] or row["user"] == "—system—":
                # System message styling
                chat_html += f"""
                <div style="
                    background-color: #f0f0f0; 
                    padding: 8px 12px; 
                    margin: 4px 0; 
                    border-radius: 8px; 
                    text-align: center; 
                    font-size: 0.9em; 
                    color: #666;
                    border-left: 3px solid #ddd;
                ">
                    {row["text"]}
                </div>
                """
            else:
                # Determine message alignment based on user
                is_my_message = row["user"] == me_user if me_user else False
                
                # Message bubble styling - narrower bubbles
                if is_my_message:
                    # Right side (my messages) - green
                    bubble_style = """
                        background-color: #DCF8C6; 
                        margin-left: 50%; 
                        margin-right: 0; 
                        border-radius: 18px 18px 4px 18px;
                        text-align: right;
                        max-width: 45%;
                    """
                    time_style = "text-align: right; margin-right: 8px;"
                else:
                    # Left side (other messages) - white
                    bubble_style = """
                        background-color: #FFFFFF; 
                        margin-left: 0; 
                        margin-right: 50%; 
                        border-radius: 18px 18px 18px 4px;
                        text-align: left;
                        border: 1px solid #E5E5E5;
                        max-width: 45%;
                    """
                    time_style = "text-align: left; margin-left: 8px;"
                
                # Format timestamp
                timestamp_str = ""
                if pd.notna(row["timestamp"]):
                    timestamp_str = row["timestamp"].strftime("%d.%m.%Y %H:%M")
                
                # Handle media attachments
                message_text = row["text"]
                is_media_message = False
                media_html = ""
                
                if row["is_media"] and "<attached:" in message_text:
                    # Extract filename from attachment
                    import re
                    match = re.search(r'<attached:\s*([^>]+)>', message_text)
                    if match:
                        filename = match.group(1).strip()
                        is_media_message = True
                        message_text = f"🎵 {filename}"
                        
                        # Check if file exists in extracted directory
                        media_dir = st.session_state.get('media_dir', '')
                        file_path = os.path.join(media_dir, filename)
                        
                        if os.path.exists(file_path):
                            # Check file size first
                            file_size = os.path.getsize(file_path)
                            if file_size == 0:
                                media_html = f"""
                                <div style="margin-top: 8px; color: #999; font-size: 0.9em;">
                                    ⚠️ Audio file is empty
                                </div>
                                """
                            else:
                                # Determine file type and create appropriate HTML
                                file_ext = os.path.splitext(filename)[1].lower()
                                
                                if file_ext in ['.opus', '.mp3', '.wav', '.m4a', '.ogg']:
                                    # Audio file - embed directly in chat with proper MIME type
                                    mime_type = "audio/opus" if file_ext == '.opus' else f"audio/{file_ext[1:]}"
                                    base64_data = get_file_base64(file_path)
                                    if base64_data:
                                        media_html = f"""
                                        <div style="margin-top: 8px;">
                                            <audio controls preload="metadata" style="width: 100%; max-width: 300px; height: 40px;">
                                                <source src="data:{mime_type};base64,{base64_data}" type="{mime_type}">
                                                <source src="data:audio/mpeg;base64,{base64_data}" type="audio/mpeg">
                                                Your browser does not support the audio element.
                                            </audio>
                                            <div style="font-size: 0.7em; color: #666; margin-top: 2px;">
                                                {file_size} bytes
                                            </div>
                                        </div>
                                        """
                                    else:
                                        media_html = f"""
                                        <div style="margin-top: 8px; color: #999; font-size: 0.9em;">
                                            ⚠️ Could not load audio file
                                        </div>
                                        """
                                elif file_ext in ['.mp4', '.avi', '.mov', '.webm']:
                                    # Video file - create clickable thumbnail with modal
                                    media_html = f"""
                                    <div style="margin-top: 8px;">
                                        <div style="
                                            background: #f0f0f0; 
                                            border: 2px dashed #ccc; 
                                            padding: 20px; 
                                            text-align: center; 
                                            border-radius: 8px; 
                                            cursor: pointer;
                                            max-width: 200px;
                                        " onclick="openMediaModal('video', '{filename}', 'data:video/mp4;base64,{get_file_base64(file_path)}')">
                                            <div style="font-size: 2em; margin-bottom: 8px;">🎥</div>
                                            <div style="font-size: 0.9em; color: #666;">Click to play video</div>
                                        </div>
                                    </div>
                                    """
                                elif file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                                    # Image file - create clickable thumbnail with modal
                                    media_html = f"""
                                    <div style="margin-top: 8px;">
                                        <img src="data:image/jpeg;base64,{get_file_base64(file_path)}" 
                                             style="max-width: 200px; max-height: 150px; border-radius: 8px; cursor: pointer;" 
                                             onclick="openMediaModal('image', '{filename}', 'data:image/jpeg;base64,{get_file_base64(file_path)}')">
                                    </div>
                                    """
                                else:
                                    # Other file types - show download link
                                    media_html = f"""
                                    <div style="margin-top: 8px;">
                                        <a href="data:application/octet-stream;base64,{get_file_base64(file_path)}" 
                                           download="{filename}" 
                                           style="color: #007bff; text-decoration: none; font-size: 0.9em;">
                                            📎 {filename}
                                        </a>
                                    </div>
                                    """
                
                # Create message bubble
                chat_html += f"""
                <div style="margin: 8px 0;">
                    <div style="{bubble_style} padding: 12px 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.1);">
                        <div style="font-weight: 500; color: #128C7E; font-size: 0.9em; margin-bottom: 4px;">
                            {row["user"]}
                        </div>
                        <div style="color: #333; line-height: 1.4; word-wrap: break-word;">
                            {message_text}
                        </div>
                        {media_html}
                    </div>
                    <div style="{time_style} font-size: 0.75em; color: #999; margin-top: 2px;">
                        {timestamp_str}
                    </div>
                </div>
                """
        
        chat_html += "</div>"
        
        # Add modal HTML and JavaScript
        modal_html = """
        <div id="mediaModal" style="
            display: none; 
            position: fixed; 
            z-index: 1000; 
            left: 0; 
            top: 0; 
            width: 100%; 
            height: 100%; 
            background-color: rgba(0,0,0,0.8);
            cursor: pointer;
        " onclick="closeMediaModal()">
            <div style="
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: white;
                padding: 20px;
                border-radius: 10px;
                max-width: 90%;
                max-height: 90%;
                cursor: default;
            " onclick="event.stopPropagation()">
                <div style="
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 15px;
                    border-bottom: 1px solid #eee;
                    padding-bottom: 10px;
                ">
                    <h3 id="modalTitle" style="margin: 0; color: #333;"></h3>
                    <button onclick="closeMediaModal()" style="
                        background: none;
                        border: none;
                        font-size: 24px;
                        cursor: pointer;
                        color: #999;
                    ">&times;</button>
                </div>
                <div id="modalContent" style="text-align: center;"></div>
            </div>
        </div>
        
        <script>
        function openMediaModal(type, filename, dataUrl) {
            const modal = document.getElementById('mediaModal');
            const title = document.getElementById('modalTitle');
            const content = document.getElementById('modalContent');
            
            title.textContent = filename;
            
            if (type === 'audio') {
                content.innerHTML = `
                    <audio controls style="width: 100%; max-width: 400px;">
                        <source src="${dataUrl}" type="audio/opus">
                        Your browser does not support the audio element.
                    </audio>
                `;
            } else if (type === 'video') {
                content.innerHTML = `
                    <video controls style="width: 100%; max-width: 600px; max-height: 400px;">
                        <source src="${dataUrl}" type="video/mp4">
                        Your browser does not support the video element.
                    </video>
                `;
            } else if (type === 'image') {
                content.innerHTML = `
                    <img src="${dataUrl}" style="max-width: 100%; max-height: 70vh; border-radius: 8px;">
                `;
            }
            
            modal.style.display = 'block';
        }
        
        function closeMediaModal() {
            document.getElementById('mediaModal').style.display = 'none';
        }
        
        // Close modal on Escape key
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                closeMediaModal();
            }
        });
        </script>
        """
        
        chat_html += modal_html
        
        # Render the scrollable chat window
        components.html(chat_html, height=620)
else:
    st.info("No messages to display with current filters.")

# Download filtered data
if not fdf.empty:
    show_cols = ["timestamp", "user", "text", "is_media"]
csv = fdf[show_cols].to_csv(index=False)
st.download_button("Download filtered CSV", data=csv, file_name="whatsapp_filtered.csv", mime="text/csv")

st.caption("v0.1 — parsing heuristics; please report odd formats you encounter.")
