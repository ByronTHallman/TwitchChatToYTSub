import atexit
import tempfile
import os # for handling download management
from CTkRangeSlider import *
import customtkinter
import tkinter
import json
import re #Used to identify chatter name colors from the json
import tkinter.font as tkfont #Monospace font for the chatlog viewer.
import bisect
import random
import copy
import threading # important for downloading
from datetime import datetime, timedelta # importing time and date to get downloaded vod dates from first message.
import yttconverter
import chat_downloader
from chat_downloader import ChatDownloader
from tkinter import filedialog, messagebox
from pathlib import Path
from dataclasses import dataclass

#--------------------------------------------------------------------------
# Exceptions
class EmptyChatError(Exception):
    """Raised when downloaded chat is evidently empty."""
    pass

class NonMediaError(Exception):
    """Raised when user attempts to download a Twitch user's profile page."""
    pass

#--------------------------------------------------------------------------
#Startup Stuff
customtkinter.set_appearance_mode("dark")
customtkinter.set_default_color_theme("dark-blue")

app = customtkinter.CTk()  # creates the window
app.geometry("1000x800")
app.resizable(False, False) #The timelines sorta break if the window is resizable.
app.title("I Played Tony Hawk's Ride Once and It Sucked")
app.focus_force()

# Colors
brightColors = [ # Some hand-picked OKLCH colors
    "#973c5d", "#964601", "#4c6c01", "#04733a",
    "#007078", "#0164a3", "#5c52a3", "#824387"]
yetDarkerColors = [ # Hand-picked darker, desaturated equivalents for visualizer.
  "#4d2634", "#5a4234", "#343d1f", "#234132",
  "#224143", "#304a5b", "#474466", "#5e4c5f"]
TwitchUserColors = ( # Random colors directly from Twitch for unassigned name colors
    "#0000FF", "#8A2BE2", "#5F9EA0", "#D2691E", "#FF7F50",
    "#1E90FF", "#B22222", "#DAA520", "#008000", "#FF69B4",
    "#FF4500", "#FF0000", "#2E8B57", "#00FF7F", "#9ACD32",)
lastColors = ["#000000", "#000000", "#000000", "#000000"] # Ensures that the last 4 colors aren't repeats

# Source management global variables
jsonData = []      # List of dictionaries for full chatlogs. "path", "name", "endTime"
currentJson = -1   # The index of the current JSON in jsonData
emptyJsonPath = Path("./Assets/Empty.json")

# Section management global variables
sections = []   # List of dictionaries. "jsonIndex", "start", "end", "button", "ogIndex", "color", "darkerColor"
currentSection = 0 # The index of the current section in sectionList

# Timeline and specific numeric global variables.
timelineMinx = 50   # The lefthand side of the timelines.
timelineMaxx = 950  # The righthand side of the timelines.
timelineMark = 8    # The delta y values of each mark on the timeline
jsonLine = 90       # The y values of the current chatlog timeline.
yttLine = 240       # The y values of the output timeline.

# Timeline slider global variables
chatlogPlayheadValue = 0      # Global variable storing first timeline playhead value for access.
outputPlayheadValue = 0       # Global variable storing second timeline playhead value for access.
#rangeSliderValues = (0, 0)   # Global variable for storing last known min and max for the section creation range slider.
rangeSliderValues = {}        # Global variable storing keys associated with tuples representing slider range values.

# Viewer global variables
viewerTimes = []                 # Stored message time values for chat viewer interaction with sliders
settingsSmallCaps = False           # Global check for if the "Small Caps" font is being used
lastChatlogMode = "Source Preview"  # Keeps track of the last used chatlog viewer mode

# Output global variables to store viewer's output mode data
outputTimes = []     # Stores all OUTPUT message times, used for bisect searching section endpoints
outputText = ""      # Pre-rendered text string
outputRanges = {}    # Pre-computed tag ranges
outputStampWidth = 0 # Pre-calculated timestamp column width
outputFirstRows = {}  # Tracks section starting times
outputUseCache = False
outputJumppoint = "playhead"

# Tempfile global variables
tempDownloads = [] #Any file downloaded by URL will be added to this list to be removed on shutdown
tempDir = tempfile.gettempdir()

#--------------------------------------------------------------------------
#Functions
#Opens JSON file picker, imports, and adds data to jsonData
def importFileJSON(importEmpty):

    # Create a placeholder "Importing..." card
    # (before filedialog process because
    #  it seems to take the longest.)
    jsonCard = customtkinter.CTkButton(
        master=jsonShelf,
        text="Importing...",
        state="disabled",  # Prevent clicking while loading
        fg_color="#374c64"  # Greyer color for loading state
    )
    jsonCard.grid(row=len(jsonData) + 1, column=0, padx=5, pady=2, sticky="ew")

    if not importEmpty:
        # Prompt user for JSON.
        filePath = filedialog.askopenfilename(
            title="Import JSON file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
    else:
        filePath = emptyJsonPath

    if not filePath:
        # Delete "Importing..."" card if import is missing.
        app.after(0, jsonCard.destroy)
        return

    # Attempt import of JSON file.
    try:
        with open(filePath, "r", encoding="utf-8") as json_file:
            imported_data = json.load(json_file)
    except (OSError, json.JSONDecodeError) as error:
        # Delete "Importing..."" card if import fails to read.
        messagebox.showerror("Import failed", f"Could not load this JSON file:\n{error}")
        app.after(0, jsonCard.destroy)
        return


    # Take stream info metadata to create chatlog label.
    json_metadata = importQueryJSON(imported_data)

    # Write label info
    json_label = f"{json_metadata['streamer']}, {json_metadata['date']}\nGame: {json_metadata['game']}"
    duration = json_metadata.get('duration', 0)

    # Warn the user if the chatlog is devoid of comments, but let them use it if they want to for some ungodly reason.
    if json_metadata.get('comments') == [] and not importEmpty:
        json_label += "\nWARNING: EMPTY"
        app.after(0, lambda: messagebox.showwarning("Import Warning", f"No messages found for this file."))

    # If some data is missing, fallback to filename.
    if(not (json_metadata['streamer'] or json_metadata['game'] or json_metadata['date'])):
        json_label = Path(filePath).stem

    # Attach this JSON to the chain of chatlog information.

    jsonData.append({"path":filePath, "name":json_label, "endTime":duration, "button": jsonCard})
    if len(jsonData) >= 2:
        #print(len(jsonData) - 1)
        jsonSelect(len(jsonData) - 1)

    # Update "Importing..." card to reflect the JSON's info.
        # "jsonData" as a list of dicts, containing: 
        # filepath, vod label, length, comments 
        # "comments" as list of dicts, containing commenter, messages, and content_offset_seconds

    if not importEmpty:
        jsonCard.configure(
            text=str(len(jsonData)-1)
            + " - " + jsonData[-1]["name"]
            + "\nDuration: "
            + "("
            + str(timedelta(seconds=duration)) + ")",
            state="normal",
            fg_color="#1f538d", hover_color="#14375e",
            command=lambda index=len(jsonData) - 1: jsonSelect(index)
        )
    else:
        jsonCard.configure(
            text=str(len(jsonData) - 1)
                 + " - " + jsonData[-1]["name"]
                 + "\nDuration: "
                 + "("
                 + "00:00:00" + ")",
            state="disabled",
            fg_color="#374c64",
            command=lambda index=len(jsonData) - 1: jsonSelect(index)
        )

    # Refresh viewer contents 
    if lastChatlogMode == "Full Sections Output":
        viewerRenderOutput(scrollTo="keep")
        viewerScroll(outputPlayheadValue)
    else:
        viewerRenderSource(keep=True)
        viewerScroll(chatlogPlayheadValue)

    # Redraw the timelines because new "current chatlog" is now different
    # And should be, by definition, blank.
    tracksRedraw()
    outputUseCache = False
    # viewerBuildOutput()
    viewerRenderAgnostic()
    # print(f"ok json current is {currentJson}")
def importEmptyJSON():
    importFileJSON(True)
def importJSON():
    importFileJSON(False)




# This works now. Make sure to build with
# this specific build of chat-downloader.
# pip install git+https://github.com/Indigo128/chat-downloader.git@all_current_fixes
def importDownloadURL():

    # Prompt user for URL
    dialog = customtkinter.CTkInputDialog(
            text="Paste the Twitch VOD URL below:",
            title="Import Twitch VOD form URL"
    )
    vod_url = dialog.get_input()

    # Exit if canceled/left blank
    if not vod_url:
        return

    # Create a placeholder "Downloading..." card
    # (Updated after successful download.)
    urlCard = customtkinter.CTkButton(
        master=jsonShelf,
        text="Downloading...\n0%",
        state="disabled",   # Prevent clicking while loading
        fg_color="#644040"  # Greyer color for loading state
    )
    urlCard.grid(row=len(jsonData)+1, column=0, padx=5, pady=2, sticky="ew")

    # Inner function for downloading via ChatDownloader library.
    def download():
        # Attempt to download chatlog via URL input.
        try:
            # == DOWNLOAD GENERATOR INIT ==
            # Download chat "generator"(?) object using ChatDownloader library.
            vod_chat = ChatDownloader().get_chat(vod_url)

            # == RAISE EXCEPTIONS ==
            # -----------------------------------------------------------
            # Raw username links lock up Chat Downloader.
            # Don't let them do that!!!
            if getattr(vod_chat, 'status', '') in ['live', 'upcoming']:
                raise NonMediaError()
            
            # Check the first message and STORE it, 
            # Messages are otherwise LOST due to how "generator"  
            # objects like "chat_downloader.sites.common.Chat" work.
            try:
                first_message = next(vod_chat)
            except StopIteration: #Nothing found, stop.
                raise EmptyChatError()
            # -----------------------------------------------------------

            #  == LABEL ==
            # Get metadata for label information.
            vod_metadata = importQueryVOD(vod_chat, first_message) #metadata dict
            vod_label = jsonWriteLabel(vod_metadata, vod_chat) #label string
            vod_duration = vod_metadata.get('duration', 0) #shortens stuff later

            # == INIT TEMPFILE ==
            # Create tempfile for storing the downloaded JSON with a relevant ID.
            vod_id = tempWriteID(vod_url)
            vod_tempfile = str(Path(tempDir) / f"temp_chat_{vod_id}.json")
            tempDownloads.append(vod_tempfile)

            # Format JSON comments into expected format for converter.
            downloaded_comments = [downloaderFormatComment(first_message)]
            for vod_message in vod_chat:
                # Formatted comment info, get time for %
                comment = downloaderFormatComment(vod_message)
                time = comment.get("content_offset_seconds")

                # Append comment to new list
                downloaded_comments.append(comment)

                # Update "Downloading..." card to represent download progress.
                percent = int(time / vod_duration * 100) if vod_duration > 0 else 0
                urlCard.configure(text=f"Downloading...\n{percent}%")

            # == CHECK FOR WEIRD TIMES ==
            # For some reason, some VODs have messages LATER 
            # than the stream length according to metadata!
            # Fall FORWARD to last comment timecode if so.
            vod_duration = downloaderCheckDuration(downloaded_comments, vod_duration)

            # == WRITE TO TEMP FILE ==
            # Dump formatted comments into a temp file,
            # allows the program to treat all chatlogs
            # agnostically between downloaded or file-imported
            with open(vod_tempfile, "w", encoding="utf-8") as f:
                json.dump({"comments": downloaded_comments}, f, ensure_ascii=False, indent=4)

        # == Exceptions ==
        # Warnings for any invalid URLs:
        except NonMediaError as error:
            app.after(0, urlCard.destroy) # delete "Downloading..." card
            app.after(0, lambda: messagebox.showwarning("Import Failed", f"Please enter a VOD or Clip URL, not a channel link."))
            return

        # Warn the user if the downloaded VOD has no comments,
        # Unfortunate, but it does happen.
        except EmptyChatError as error:
            app.after(0, urlCard.destroy) # delete "Downloading..." card
            app.after(0, lambda: messagebox.showwarning("Import Failed", f"No messages found for this VOD:\n{vod_url}"))
            return

        # Any other errors.
        except Exception as error:
            app.after(0, urlCard.destroy) # delete "Downloading..." card
            app.after(0, lambda: messagebox.showerror("Import Failed for Unknown Reasons", f"Could not fetch chat from URL:\n{vod_url}"))
            return

        # Inner INNER function:
        # If successful download, attach VOD info to chatlog chain "jsonData".
            # "jsonData" as a list of dicts, containing: 
            # filepath, vod label, length, comments 
            # "comments" as list of dicts, containing commenter, messages, and content_offset_seconds 
        def update_ui():
            jsonData.append({"path": vod_tempfile, "name": vod_label, "endTime": vod_duration, "comments": downloaded_comments, "button": urlCard})
            if len(jsonData) >= 1:
                jsonSelect(len(jsonData) - 1)

            # Update the "downloading" label to reflect the VOD's information
            urlCard.configure(
                text=str(len(jsonData)) 
                + " - " + jsonData[-1]["name"] 
                + "\nDuration: " 
                + "(" 
                + str(timedelta(seconds=vod_duration)) + ")",
                state="normal",
                fg_color="#7a2b2b", hover_color="#5c1e1e",
                command=lambda index=len(jsonData) - 1: jsonSelect(index)
            )

        # Update UI after thread completes.
        app.after(0, update_ui)

    # Refresh viewer contents 
    if lastChatlogMode == "Full Sections Output":
        viewerRenderOutput(scrollTo="playhead")
        viewerScroll(outputPlayheadValue)
    else:
        viewerRenderSource(keep=True)
        viewerScroll(chatlogPlayheadValue)

    # Redraw the timelines because new "current chatlog" is now different
    # And should be, by definition, blank.
    tracksRedraw()
    outputUseCache = False
    #viewerBuildOutput()
    viewerRenderAgnostic()

    # Entire program froze during download 
    # unless threading was brought in.
    threading.Thread(target=download, daemon=True).start()

    #print(f"ok json current is {currentJson}")


#--------------------------------------------------------------------------
# CHATLOG / SECTION MANAGEMENT
#--------------------------------------------------------------------------
# Visualizer
#Chatlog Viewer. A scrollable list: timestamp on the left, then the colored name and the message. Section text is highlighted as a block.
# TODO: Move this up top with the rest of the global variables.
DEFAULT_COLOR = "#bbbbbb" #Used when a chatter has no color in the json
viewerSection = -1 #Index in sectionList of the selected section, or -1 when a plain chatlog is shown
#rename from
editedOnly = False #True = hide every message that isn't inside a section

# TODO: Group this with helper functions
#Used to sort messages by their time. 
# "message" is 
    # (seconds, name, body, name color), 
def viewerGetMessageTime(message):
    # so time in "seconds" is the [0]th item.
    return message[0]

#Reads one comment and returns (seconds, name, body, color), or None if it can't be read.
#Twitch json files use content_offset_seconds / commenter / message.body / message.user_color.
#Chat-downloader style files use time_in_seconds / author / message (plain text) / author.colour.
    # Note from Kai: the ImportURL function automatically converts to the first style, 
    # though it doens't hurt to be thorough...
def viewerParseComment(comment):
    # Change: Shrunk assignments to one line
    # Feel free to revert if prefer speed bump design, should behave more or less the same
    # (Except for the random color rule, that's new)

    seconds = comment.get("content_offset_seconds", comment.get("time_in_seconds"))       
    # Timeless messages are useless, give up 
    if seconds is None:
        return None
    
    message = comment.get("message", "")
    body = message.get("body", "") if isinstance(message, dict) else message
    name = comment.get("commenter", {}).get("display_name", comment.get("author", {}).get("display_name", ""))
    color = (message.get("user_color") if isinstance(message, dict) else None) or comment.get("author", {}).get("colour")

    #A valid color looks like #1E90FF. Anything else (missing, null, odd text) gets the default color.
    if color is None or re.fullmatch(r"#[0-9a-fA-F]{6}", str(color)) is None:
        color = random.choice(TwitchUserColors) #take a random color from Twitch defaults global string list
    return (seconds, str(name), str(body).replace("\n", " "), color)

#Returns a sorted list of (seconds, name, body, name color) for one imported chatlog.
def viewerLoadMessages(index):
    jsonEntry = jsonData[index]
    if "cached_messages" in jsonEntry:
        return jsonEntry["cached_messages"] #Prevent re-loading an already parsed JSON file
    
    comments = jsonEntry.get("comments") #URL imports already hold their comments in memory (for some reason. why don't we do this with file imports?)
    if comments is None:
        try:
            with open(jsonEntry["path"], "r", encoding="utf-8") as json_file:
                data = json.load(json_file)
        except (OSError, json.JSONDecodeError) as error:
            messagebox.showerror("Viewer error", f"Could not read this chatlog:\n{error}")
            return []
        if isinstance(data, list):
            comments = data #some files are only a list of comments
        else:
            comments = data.get("comments", [])

    messages = []
    for comment in comments:
        try:
            parsed = viewerParseComment(comment) #seconds, name, body, color
        except (TypeError, AttributeError):
            continue #skip comments that aren't shaped like we expect
        if parsed is not None:
            messages.append(parsed)

    messages.sort(key=viewerGetMessageTime)
    jsonEntry["cached_messages"] = messages #Prevent re-loading an already parsed JSON file
    return messages

#Sections is a list of (position in sectionList, section dict) for this chatlog.
#Returns (rows, firstRow). rows is a list of (timestamp, name, name color, body, tag), tag is "out" or "sec<position>".
#firstRow maps position -> index of that section's first row.
def viewerBuildSource(messages, sections, selected, editedOnlyMode):
    rows = []
    firstRow = {}
    timeList = [] # let's not throw time away
    for time, name, body, darkerColor in messages:
        #Collect every section that contains this message.
        #print(t)
        matchingSections = []
        for position, section in sections:
            if section["start"] <= time <= section["end"]:
                matchingSections.append(position)

        if len(matchingSections) > 0: #Find AT LEAST one section that overlaps this message
            #In cases of a selected section already having a color, the color will not change
            chosenPosition = matchingSections[0]
            for position in matchingSections:
                if position == selected:
                    chosenPosition = position
            tag = "sec" + str(chosenPosition)
            if chosenPosition not in firstRow: #don't rewrite firstRow for every single row, just the first one?
                firstRow[chosenPosition] = len(rows) #remember where this section first shows up, and NEVER do it again?
        else: #Message is outside ALL cuts, label accordingly
            if editedOnlyMode:
                continue #If in viewer mode 2, stop the entire loop and stop rendering past the section
            tag = "out"

        rows.append((helpSecToString(int(time)), name, darkerColor, body, tag))
        timeList.append(int(time)) # keep the time values to inform the highlighted message mechanic #changed float to int

    return rows, firstRow, timeList # !!! catch time values to put into viewerMessageTimes

#Turns rows into the text to insert and the character ranges to tag.
#Returns (text, ranges, stampWidth). ranges maps tag -> list of (line, startColumn, endColumn), lines start at 1.
def viewerBuildText(rows):
    #Find the longest timestamp so the timestamp column lines up.
    stampWidth = 0
    for row in rows:
        if len(row[0]) > stampWidth:
            stampWidth = len(row[0])

    lines = []
    ranges = {}

    #Adds one (line, startColumn, endColumn) range to a tag's list, creating the list the first time.
    def AddRange(tag, row, startColumn, endColumn):
        if tag not in ranges:
            ranges[tag] = []
        ranges[tag].append((row, startColumn, endColumn))
    
    for row, (stamp, name, color, body, tag) in enumerate(rows, start=1): # iterate across rows, start at 1
        head = stamp.ljust(stampWidth) + "  "
        label = name + ":"
        content = label + " " + body
        is_header = name.startswith("=====")
        if not is_header:
            content = viewerSmallCapsPass(content)
        line = head + content #in case the Small Caps font is used, reformat the preview text accordingly
        nameStart = len(head)
        nameEnd = nameStart + len(label)
        lines.append(line)
        AddRange("timestamp", row, 0, stampWidth)
        if is_header:
            AddRange("header", row, nameStart, len(line))
        AddRange("name" + color[1:], row, nameStart, nameEnd) #one tag per name color, like nm1E90FF
        if tag == "out":
            AddRange(tag, row, nameEnd, len(line)) #only the message text is gray
        else:
            AddRange(tag, row, 0, None) #the whole line, so the section is highlighted as a block

    # Concatenate every line with \n, return as (all rows, ranges, widths)
    return "\n".join(lines), ranges, stampWidth

def viewerRender(keep=False, scroll=False, scrollTo="top", mode="source"):
    # Tag meanings:
    # "secN" = message section of section N
    # "headerN" = section header row for section N
    # "timestamp" = self explanatory
    # "out" = message is not in a section
    # "hang" = a message is indented, remainder pushed onto additional lines
    # "nm123456" = color tags, where 123456 are hex code values
    # "active_highlight" = message is scrolled onto and highlighted

    # == GLOBALS ==
    global viewerSection, viewerTimes, outputPlayheadValue
    mode = viewerModeButtons.get()

    # Store preview view position. Unsure if this is ever used.
    previous = viewer.yview()[0]

    # Temporary
    if keep:
        scrollTo = "keep"
    if scroll:
        scrollTo = "section"

    if mode == "Full Sections Output":
        viewerBuildOutput()  # Does nothing if outputUseCache is True
        text = outputText
        ranges = outputRanges
        stampWidth = outputStampWidth
        firstRow = outputFirstRows
        viewerTimes = outputTimes
    else:  
        if currentJson < 0 or currentJson >= len(jsonData): # Give up if currentJson has invalid index
            return


#Redraws the viewer from currentJson / viewerSection / editedOnly.
#scroll=True jumps to the selected section. keep=True stays at the current scroll position.
def viewerRenderSource(scroll=False, keep=False, scrollTo="top"):
    # Tag meanings:
    # "secN" = message section of section N
    # "headerN" = section header row for section N
    # "timestamp" = self explanatory
    # "out" = message is not in a section
    # "hang" = a message is indented, remainder pushed onto additional lines
    # "nm123456" = color tags, where 123456 are hex code values
    # "active_highlight" = message is scrolled onto and highlighted

    # Temporary
    if keep:
        scrollTo = "keep"
    if scroll:
        scrollTo = "section"

    # == GLOBALS ==
    global viewerSection, viewerTimes # need to catch the times for highlighted comment mechanic
    
    # Give up if currentJson has invalid index
    if currentJson < 0 or currentJson >= len(jsonData):
        return
    # Reset "viewerSection" global if invalid
    if ((viewerSection < 0 or viewerSection >= len(sections)) # is viewerSection out of bounds?
        or (sections[viewerSection]["jsonIndex"] != currentJson)): # pointing to a different section?
            viewerSection = -1

    # Store preview view position. Unsure if this is ever used.
    previous = viewer.yview()[0]

    # == FILTER SECTIONS ==
    # Collect the sections that belong to the chatlog being shown, 
    # along with their position in sectionList.
    filteredSections = []
    for sectionListIndex, section in enumerate(sections):
        if section["jsonIndex"] == currentJson:
            filteredSections.append((sectionListIndex, section))
    rows, firstRow, viewerTimes = viewerBuildSource(viewerLoadMessages(currentJson), filteredSections, viewerSection, editedOnly)

    # == EMPTY CHATLOG? ==
    if not rows:
        rows = [("", "", "#bbbbbb", "No sections in this chatlog yet." if editedOnly else "This chatlog has no messages.", "out")]
    text, ranges, stampWidth = viewerBuildText(rows)

    # == START RENDER ==
    viewer.configure(state="normal") # enable editing to change the text
    viewer.delete("1.0", "end") # DELETES THE ENTIRE VIEWER'S CONTENTS LOL

    for sectionListIndex, section in filteredSections:
        viewer.tag_config("sec" + str(sectionListIndex), background=section["darkerColor"], foreground="#ffffff")

    # == INSERT TEXT INTO VIEWER ==
    viewer.insert("1.0", text)
    viewer.tag_add("hang", "1.0", "end") # Apply hang tag to everything

    # == FORMATTER ==
    for tag, spans in ranges.items():
        if tag.startswith("name"):
            viewer.tag_config(tag, foreground="#" + tag[4:])
            viewer.tag_raise(tag) #name color must win over the block's white text
        indexes = []
        for line, startColumn, endColumn in spans:
            indexes.append(f"{line}.{startColumn}")
            if endColumn is None:
                indexes.append(f"{line + 1}.0") #start of the next line, so the line break is included
            else:
                indexes.append(f"{line}.{endColumn}")
        for i in range(0, len(indexes), 2000): #tag many ranges per call, much faster than one by one
            viewer.tag_add(tag, *indexes[i:i + 2000])

    viewer.tag_raise("timestamp")
    viewer.tag_raise("active_highlight")

    # == STOP RENDER ==
    viewer.configure(state="disabled")

    if scrollTo == "keep":
        viewer.yview_moveto(previous) 

    elif scrollTo == "top":
        viewer.yview_moveto(0)

    elif scrollTo == "playhead":
        viewerScroll(chatlogPlayheadValue)

    elif ((scrollTo == "section")
        and (viewerSection in firstRow)):
            targetTime = viewerTimes[firstRow[viewerSection]]
            viewerScroll(targetTime)

    else:
        # ???
        return

#Moved viewerRenderOutput
def viewerRenderOutput(scrollTo="top"):
    # Tag meanings:
    # "secN" = message section of section N
    # "headerN" = section header row for section N
    # "timestamp" = self explanatory
    # "out" = message is not in a section
    # "hang" = a message is indented, remainder pushed onto additional lines
    # "nm123456" = color tags, where 123456 are hex code values
    # "active_highlight" = message is scrolled onto and highlighted

    print(f"{outputUseCache}")
    print(f"viewerRenderOutput: viewerSection is {viewerSection}")
    print(f"viewerRenderOutput: scrollTo is {scrollTo}")

    viewerBuildOutput()

    # == GLOBALS ==
    global viewerTimes, outputPlayheadValue

    # Update viewerTimes for Output mode.
    viewerTimes = outputTimes

    # Store preview view position. Unsure if this is ever used.
    previous = viewer.yview()[0]

    # Edit prep
    viewer.configure(state="normal") # enable editing to change the text
    viewer.delete("1.0", "end") # DELETES THE ENTIRE VIEWER'S CONTENTS LOL

    # Position for section number, section as corresponding dictionary itself
    for sectionListIndex, section in enumerate(sections):
        viewer.tag_config("sec" + str(sectionListIndex), background=section["darkerColor"], foreground="#ffffff")

    # == INSERT TEXT INTO VIEWER ==
    viewer.insert("1.0", outputText)
    viewer.tag_add("hang", "1.0", "end") # Apply hang tag to everything

    # == FORMATTER ==
    for tag, spans in outputRanges.items(): #outputRanges exists so that re-calculating isnt necessary every single reorder or tab switch
        if tag.startswith("name"):
            viewer.tag_config(tag, foreground="#" + tag[4:])
            viewer.tag_raise(tag)
        indexes = []
        for line, startColumn, endColumn in spans:
            indexes.append(f"{line}.{startColumn}")
            if endColumn is None:
                indexes.append(f"{line + 1}.0")
            else:
                indexes.append(f"{line}.{endColumn}")
        for i in range(0, len(indexes), 2000):
            viewer.tag_add(tag, *indexes[i:i + 2000])
            
    viewer.tag_raise("timestamp") # Enforce text color on timestsamps
    viewer.tag_raise("active_highlight") # Overwrite section color with highlight

    # == STOP RENDER ==
    viewer.configure(state="disabled")

    if scrollTo == "keep":
        viewer.yview_moveto(previous)

    elif scrollTo == "top":
        viewer.yview_moveto(0)

    elif scrollTo == "playhead":
        viewerScroll(outputPlayheadValue)

    elif (scrollTo == "section") and (0 <= viewerSection < len(sections)):
        firstRows = getSectionStarts()
        print(f"viewerRenderOutput firstRows: {firstRows}")
        targetTime = firstRows[viewerSection]
        timelinesOutputSlider.set(targetTime)
        outputPlayheadValue = targetTime
        tracksRefreshPlayheads()
        viewerScroll(targetTime) #neither of these work

    else:
        # ???
        return

# Output preview related functions
def viewerBuildOutput():
    global outputText, outputRanges, outputStampWidth
    global outputTimes, outputUseCache

    print(f"len of sections is {len(sections)}")
    
    if outputUseCache:
        return # Don't update output cache variables
    
    starts = getSectionStarts() # Get list of starts
    outputTimes = []            # Reset output times
    #outputFirstRows = {}        # Reset dict of each section's first row index
    rows = []                   # Init rows
    
    for i, section in enumerate(sections):
        messages = viewerLoadMessages(section["jsonIndex"])
        if not messages:
            continue

        # Add visual indicator of sections moved around
        ogIndex = (section.get("ogIndex", -1) + 1)
        shiftedIndication = ""
        if (i) != ogIndex:
            shiftedIndication = f"({ogIndex + 1})"

        # Add section 
        header_t = starts[i]
        header_name = f"====== SECTION {i + 1}{shiftedIndication}"
        header_color = "#FFFFFF"
        header_body = f"START ======"
        
        #outputCache.append((header_t, header_name, header_color, header_body))
        outputTimes.append(float(header_t))
        rows.append((helpSecToString(int(header_t)), header_name, header_color, header_body, f"sec{i}"))
        
        sectStart = section["start"] #wait, isn't this redundant...?
        sectEnd = section["end"]
        
        # Fast bisect slicing to find endpoints of sections
        # instead of parsing every message directly
        # O(N) -> O(log N)
        left_idx = bisect.bisect_left(messages, (sectStart,))
        right_idx = bisect.bisect_right(messages, (sectEnd,))
        time_offset = starts[i] - sectStart
        
        for msg in messages[left_idx:right_idx]:
            t, name, body, color = msg
            #name = name
            #body = body
            shifted_t = t + time_offset
            #outputCache.append((shifted_t, name, color, body))
            outputTimes.append(int(shifted_t))
            rows.append((helpSecToString(int(shifted_t)), name, color, body, f"sec{i}")) #tags each message with corresponding section index
        
    if not rows:
        rows = [("", "", "#bbbbbb", "No sections in output timeline.", "out")]

    # Update output global variables
    outputText, outputRanges, outputStampWidth = viewerBuildText(rows)

    # Next time, use this cache unless otherwise stated.
    #print(f"[{outputText}]")
    if outputText != "  : No sections in output timeline.":
        print("yay")
        outputUseCache = True

def rangeStore(rangeSlider, index):
    values = rangeSlider.get() or [0, 100] #default to [0, 100] if range isn't stored
    rangeSliderValues[index] = (values[0], values[1], rangeSlider.cget("to")) #add positions and endpoint

def rangePull(index):
    rangeTriple = (0, 100, 100) #Default values

    if index in rangeSliderValues:
        rangeTriple = rangeSliderValues.get(index) # Take stored ranges if available
    elif -1 < index < len(jsonData):
        endTime = jsonData[index].get("endTime", 100) # Normal case of new source, take endTime.
        rangeTriple = (0, endTime, endTime)
    else:
        print("...There's no sources. How did you even get here?") # currentJson == -1, No sources.
        print("...Well, I guess you didn't import anything. Weirdo.") # Wait, this should be impossible.
        print("Warning: No Range Values Available")                     # The only call can't reach this...

    return rangeTriple

def rangeManagement(index):
    if(currentJson > -1): #Shouldn't have to check for this, but whatever
        if(currentJson != index): # are we not clicking a JSON we are already looking at?
            #1. store stupid current slider state
            rangeStore(rangeSlider, currentJson) # adds a triple to rangeSliderValues: (left, right, and length) from CURRENT json

            #2. pull dumb state for new json key 
            rangeLeft, rangeRight, rangeLimit = rangePull(index) # PULLS a triple, left, rights, lenght; defaults to (0, 100, 100)

            #3. set the sliders in the right place. and markers
            rangeSlider.configure(to=rangeLimit)    # set limit
            rangeSlider.set((rangeLeft, rangeRight))  # set handles
            rangeMoveMarker(rangeLeft, "left")
            rangeMoveMarker(rangeRight, "right")

            #4. update boxes
            rangeUpdateBoxes(hourStart, minStart, secStart, rangeLeft)
            rangeUpdateBoxes(hourEnd, minEnd, secEnd, rangeRight)
        else:
            print("Warning: Clicking Already Open JSON, what are you doing?") # currentJson == index
            print(f"RangePull LOG CurrentJson: {currentJson}")
            print(f"RangePull LOG Index: {index}")

    else:
        #print("rangemanagement here, hey your current json is -1")
        if index < len(jsonData):
            endTime = jsonData[index]["endTime"] #first JSON is a special case
        else:
            return
        #1. move sliders and markers
        rangeSlider.configure(to=endTime)
        rangeSlider.set((0, endTime)) # Reset knobs to start and end
        rangeMoveMarker(0, "left")
        rangeMoveMarker(endTime, "right")
        #2. update boxes
        rangeUpdateBoxes(hourStart, minStart, secStart, 0)
        rangeUpdateBoxes(hourEnd, minEnd, secEnd, endTime)

    for key, (val1, val2, val3) in rangeSliderValues.items():
        print(f"{key}: {val1}, {val2}, {val3}")

def jsonHighlight():
    for i, entry in enumerate(jsonData):
        if i == currentJson:
            entry["button"].configure(border_width=3, border_color="#ff8181")
        else:
            entry["button"].configure(border_width=0)

#Change 11/8/26: SelectJson now also tells the viewer which chatlog to show.
#Renamed to jsonSelect
def jsonSelect(index):
    # TODO write current range slider handles to tuples and assign to dict with currentJson as key before reassignment
    global currentJson, viewerSection

    rangeManagement(index)
    currentJson = index
    jsonHighlight()

    viewerSection = -1 
    viewerRenderSource() #Draw it.
    if lastChatlogMode == "Full Sections Output":
        viewerScroll(outputPlayheadValue)
    else:
        viewerScroll(chatlogPlayheadValue)
    rangeSourceTitle.configure(
        text="Current Source: " + jsonData[currentJson]["name"]
    )

    # Force text boxes to match the new reset slider
    # SectionSliderDragged([0, endTime])

    # Update timeline to reflect selected JSON
    # Update timeline playheads to match current state
    tracksRedraw()
    outputUseCache = False
    #viewerBuildOutput()
    viewerRenderAgnostic(scroll=True, scrollTo="playhead")

def sectionHighlight():
    for i, section in enumerate(sections):
        if i == currentSection:
            section["button"].configure(border_width=3, border_color="#B2FFB8")
        else:
            section["button"].configure(border_width=0)    

def sectionCreate(isEmpty):
    global currentJson
    print(f"this is idiotic., whats the current json {currentJson}")
    if isEmpty: #tempCurrentJson stores the last value of currentJson so that it can be restored after the empty section is created.
        tempCurrentJson = currentJson
        currentJson = 0
    else:
        tempCurrentJson = currentJson
    if currentJson == -1:
        return

    try:
        if not isEmpty:
            hourS = int(hourStart.get() or "0") #or "0" for when text entry is left empty
            minS = int(minStart.get() or "0")
            secS = float(secStart.get() or "0")
            hourE = int(hourEnd.get() or "0")
            minE = int(minEnd.get() or "0")
            secE = float(secEnd.get() or "0")
        else:
            hourS = 0
            minS = 0
            secS = 0.0
            hourE = int(hourEmpty.get() or "0")
            minE = int(minEmpty.get() or "0")
            secE = float(secEmpty.get() or "0")

    except ValueError:
        messagebox.showwarning("Invalid Input", "Please enter valid numbers for the timestamp.")
        return

    start = helpStampToSec(hourS,minS,secS)
    end = helpStampToSec(hourE,minE,secE)
    maxEnd = jsonData[currentJson]["endTime"]

    #Update endpoint depending on validity of inputs.
    end = sectionValidEnds(start, end, maxEnd)
    if(end == 0):
        return

    colorID = sectionGenColor()
    rangeCreateButton.configure(fg_color = brightColors[colorID])
    sectionButton = customtkinter.CTkButton(
        master=sectionShelf,
        text=str(len(sections) + 1) + " - " + jsonData[currentJson]["name"] + "\n" + helpSecToString(start) + " - " + helpSecToString(end),
        command=lambda index=len(sections): sectionSelect(index)
    )
    sectionButton.configure(fg_color = brightColors[colorID], hover = False)                #note: ogIndex does not seem to do anything yet
    sections.append({"jsonIndex":currentJson, "start":start, "end":end, "button":sectionButton, "ogIndex":(len(sections) - 1), "color":brightColors[colorID], "darkerColor":yetDarkerColors[colorID]})
    sectionButton.grid(row=len(sections), column=0, padx=5, pady=5, sticky="nsew")

    sectionSelect(len(sections) - 1) #Note: Len makes a list of 1 object have a len value of 1
    currentJson = tempCurrentJson

    global outputUseCache
    outputUseCache = False

    # "Select" the newly created section, handle internally which viewer is open
    print(f"gonna select {len(sections) - 1}")
    sectionSelect(len(sections) - 1) #Note: Len makes a list of 1 object have a len value of 1

    #Redundant with sectionSelect
''' tracksRedraw()
    viewerBuildOutput()
    viewerRenderAgnostic(scroll=True)'''

    #print(f"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA {len(sections)}")

    #print(f"CHATLOG PLAYHEAD {chatlogPlayheadValue}")

    #if(viewerModeButtons.get() == "Full Sections Output"):
    #    ScrollViewer(outputPlayheadValue)
    #else:
    #    ScrollViewer(chatlogPlayheadValue)
#Callback functions for creating sections
def sectionCreateNormal():
    sectionCreate(False)
def sectionCreateEmpty():
    sectionCreate(True)

def sectionSelect(index):
    global currentSection, currentJson, viewerSection
    global outputUseCache, outputJumppoint

    print(f"index is {index}")

    # == UPDATE CURRENT SECTION ==
    # Update currentSection. if index starts at 0, len of sectionList should be 1
    # ALSO updates viewerSection
    if -1 < index < len(sections):
        currentSection = index
        viewerSection = index
        sectionHighlight()
    else:
        sectionHighlight()
        tracksRedraw()
        viewerRenderAgnostic(scrollTo="top")
        return

    print(f"len(sections) is {len(sections)}")

    # == UPDATE CURRENT JSON ==
    #selected section might be on a different chatlog
    #update timeline to reflect this
    jsonIndex = sections[index]["jsonIndex"]
    if(currentJson != jsonIndex):
        rangeManagement(jsonIndex)
        #(f"currentJson: {currentJson}")
        #print(f"jsonIndex: {jsonIndex}")
        currentJson = jsonIndex
        jsonHighlight()
        rangeSourceTitle.configure(text="Current Source: " + jsonData[currentJson]["name"])

    # == UPDATE TIMELINE, WHICH UPDATES VIEWER ==
    tracksRedraw()
    outputUseCache = False
    outputJumppoint = "section" # next switch to output will emphasize "section"
    #viewerBuildOutput()
    viewerRenderAgnostic(scroll=True, scrollTo="section")

def sectionSwap(index1, index2):
    global sections, outputUseCache, viewerSection, currentSection
    outputUseCache = False

    # Swap button commands and grid positions
    sections[index1]["button"].configure(command=lambda index=index2: sectionSelect(index)) #swapping lamda commands
    sections[index2]["button"].configure(command=lambda index=index1: sectionSelect(index))
    sections[index1]["button"].grid(row=index2 + 1) #swapping location in sectionEditor
    sections[index2]["button"].grid(row=index1 + 1) #+1 to account for title label

    # Swap list elements
    sections[index1], sections[index2] = sections[index2], sections[index1] #swapping sectionList elements using tuple unpacking

    currentSection = index2
    viewerSection = index2
    sectionHighlight()
    tracksRedraw()
    viewerRenderAgnostic(scrollTo="section")
    return

def sectionDelete(index):
    global sections, currentSection, viewerSection, outputUseCache
    if not sections or not (0 <= index < len(sections)):
        return

    sections[index]["button"].destroy() # eliminate section visual
    sections.pop(index)              # eliminate section data

    for i, section in enumerate(sections):
        section["button"].configure(command=lambda target=i: sectionSelect(target))
        section["button"].grid(row=i + 1)

    if not sections:
        currentSection = 0
        viewerSection = -1
        sectionHighlight()
        tracksRedraw()
        viewerRenderAgnostic(scrollTo="top")
    else:
        currentSection = min(index, len(sections) - 1)
        viewerSection = currentSection
        sectionSelect(currentSection)

# Ensures section colors aren't repeated in sequence.
def sectionGenColor():
    global lastColors
    colorID = random.randint(0, 7)
    while brightColors[colorID] in lastColors:
        colorID = random.randint(0, 7)
    lastColors.pop(0)
    lastColors.append(brightColors[colorID])
    return colorID

# Checks whether the section timestamps make sense, and updates the end accordingly.
# Seems to be a less friction-inducing implementation.
def sectionValidEnds(start, end, maxEnd): 
    if(maxEnd) <= 0 or (start >= maxEnd):
        messagebox.showwarning("Invalid Section", "Specified time can only create section of zero seconds, please try again.")
        return 0
    if start > end or start < 0 or end < 0:
        messagebox.showwarning("Section Warning", "Please make sure your start is not before your end.\n\nSetting end to maximum length.")
        return maxEnd
    elif(end > maxEnd):
        messagebox.showwarning("Section Warning", "Specified time longer than chatlog.\n\nSetting end to maximum length.")
        return maxEnd
    elif start == end:
        messagebox.showwarning("Section Warning", "Section is zero seconds long!\n\nSetting end to maximum length.")
        return maxEnd

    # Leave end unchanged if valid.
    return end

#--------------------------------------------------------------------------
#Callback functions that call KeyPress (used for the shifting and deleting section buttons)
def callUp():
    app.event_generate("<Up>")
def callDown():
    app.event_generate("<Down>")
def callDelete():
    app.event_generate("<Delete>")

#--------------------------------------------------------------------------
# Parsing helper functions

def helpStampToSec(hours, minutes, seconds):
    sec = hours * 3600 + minutes * 60 + seconds
    return sec

def helpSecToString(seconds):
    hours = int(seconds // 3600)
    seconds = seconds % 3600
    minutes = int(seconds // 60)
    seconds = seconds % 60
    if seconds % 1 == 0:
        # If whole number seconds.
        return f"{hours:02}:{minutes:02}:{int(seconds):02}"
    else:
        # If there are fractional seconds. Take off unnecessary zeroes from the right.
        return f"{hours:02}:{minutes:02}:{seconds:05.2f}".rstrip('0')

#--------------------------------------------------------------------------
# Formatting helper functions

# Takes downloaded Twitch chat
# and formats it to best fit the
# style that the rest of this program expects.
def downloaderFormatComment(comment):
    return {
        'commenter': {
                'display_name': comment.get('author', {}).get('display_name', '')
        },
        'message': {
                'body': comment.get('message', ''),
                'user_color': comment.get('author', {}).get('colour')
        },
        'content_offset_seconds': comment.get('time_in_seconds', 0.0)
    }

# Writes the string for the Chatlog list labels.
def jsonWriteLabel(metadata, vod_chat):
    # TODO: Make the logical organization of this less ridiculously stupid.
    if vod_chat:
        media_type = getattr(vod_chat, 'video_type', 'unknown')
        if media_type == "video":
            return f"{metadata['streamer']}, {metadata['date']}\nGame: {metadata['game']}"
        elif media_type == "clip":
            return f"Clip: {metadata['date']}"
        else:
            return f"Invalid Chatlog"
    else:
        return f"{metadata['streamer']}, {metadata['date']}\nGame: {metadata['game']}"

# Some VODs have a strange quirk where 
# messages go further than VOD metadata suggests.
# Fall back to last message as max length if so.
def downloaderCheckDuration(comments, duration):
    if not comments:
        return duration
    elif(comments[-1].get('content_offset_seconds') > duration):
        return comments[-1].get('content_offset_seconds')
    else:
        return duration

#--------------------------------------------------------------------------
# Global timing info helper functions

# Returns the total time elapsed in the output file.
def getYTTDuration():
    totalTime = 0
    for section in sections:
        totalTime += section["end"] - section["start"] #+ 1 I don't really understand this +1 so removing it, very sorry #times are inclusive so I'm adding 1
    return totalTime

# Returns a list of all the starting times of the sections relative to each cumulative addition.
def getSectionStarts():
    totalTime = 0
    starts = []
    for section in sections:
        starts.append(totalTime)
        totalTime += section["end"] - section["start"] #+ 1 I don't really undestand this +1 so removing it, very sorry #times are inclusive so I'm adding 1
    starts.append(totalTime)
    return starts

#--------------------------------------------------------------------------
# Import/download-related helper functions

# For tempfile management, extracts VOD ID for use as a backend label.
def tempWriteID(vod_url):
    # Filename handling for downloaded temp files, based on vod ID number.
    if "www.twitch.tv/" and "videos/" in vod_url:
        return vod_url.strip().split("videos/")[-1].split("?")[0]
    elif "www.twitch.tv/" and "/clip/" in vod_url:
        return vod_url.strip().split("clip/")[-1].split("?")[0]
    elif "clips.twitch.tv/" in vod_url:
        return vod_url.strip().split("clips.twitch.tv/")[-1].split("?")[0]
    else:
        return str(random.randint(1, 1000000))

# Pokes around the esoteric Chat-Downloader backend to try and get
# things like game data and streamer name for the Chatlog labels.
# Returns a dictionary for the label.
def importQueryVOD(vod_chat, first_message):

    # Run query for metadata.
    vod_query = [{'operationName': 'VideoMetadata', 'variables': {'channelLogin': '', 'videoID': vod_chat.id}}]
    vod_data = vod_chat.site._download_gql(vod_query)[0]['data']['video']

    # Build label elements for "Imported Chatlogs" UI.
    vod_streamer = vod_data.get('owner', {}).get('displayName') if vod_data else "Unknown"
    vod_game = vod_data.get('game', {}).get('displayName') if vod_data and vod_data.get('game') else "Unknown"
    vod_utc = first_message.get('timestamp', 0)
    vod_date = datetime.fromtimestamp(vod_utc / 1000000).strftime(f"%m/%d/%y")
    vod_duration = getattr(vod_chat, 'duration', 0)

    # Clips struggle to provide information, so force some formatting.
    media_type = getattr(vod_chat, 'video_type', 'unknown')
    if media_type == "clip":
        streamer = 'Clip'

    # Return as metadata dictionary.
    return {
        "streamer": vod_streamer,
        "game": vod_game,
        "date": vod_date,
        "duration": vod_duration
    }

# Parses the imported JSON file to find information
# like streamer name, game name.
# If those can't be found, handle it accordingly.
# Return dictionary for the label. Return comments in dictionary as well
# in order to account for malformed "list" style chatlog JSONs with only chat.
def importQueryJSON(imported_data, json_comments = []):

    # Handling weird formatting in some JSON files.
    if type(imported_data) == list:
        # Some JSON downloaders seem to download as a list of comments only.
        # Force format to being a dictionary. Turn JSON list into the 'comments' block.
        json_comments = imported_data
        imported_data = {'comments': imported_data}
    else:
        json_comments = imported_data.get('comments', []) if imported_data else None

    # Extract higher level data.
    json_video_data = imported_data.get('video') if imported_data else None
    json_streamer_data = imported_data.get('streamer') if imported_data else None
    json_chapter_data = json_video_data.get('chapters', []) if json_video_data else None

    # Define date.
    json_date_data = str(json_video_data.get('created_at')) if json_video_data else None
    json_date_part = json_date_data.split("T")[0] if json_date_data else '00-00-00'
    year, month, day = json_date_part.split("-")

    # Create label. Get duration from metadata, otherwise fall back to last message time value.
    json_streamer = json_streamer_data.get('name') if json_streamer_data else 'Unknown'
    json_game = json_chapter_data[0].get('gameDisplayName') if json_chapter_data and len(json_chapter_data) > 0 else 'Unknown'
    json_date = f"{month}/{day}/{year[-2:]}" if json_date_data != None else 'Unknown Date'
    json_lastmsg = json_comments[-1] if json_comments else None
    json_lastsec = json_lastmsg.get("content_offset_seconds", json_lastmsg.get("time_in_seconds", 0)) if json_comments else 0
    json_duration = json_video_data.get('end', 0) if json_video_data else json_lastsec

    # There are some strange cases where 
    # chat message timestamps extend beyond metadata stream length.
    if(json_lastsec > json_duration):
        json_duration = json_lastsec

    # Return as metadata dictionary, along with "comments" to be parsed for time.
    return{
        'streamer': json_streamer,
        'game': json_game,
        'date': json_date,
        'duration': json_duration,
        'comments': json_comments
    }

#--------------------------------------------------------------------------
# Exporting
# The primary merging implementation, sends data to Berrin's converter and executes it. 
def exportYTT():
    if len(sections) == 0:
        messagebox.showwarning("Export Error", "No sections have been added to the timeline.")
        return

    # Ask the user for where to save the output and as what?
    output_path = filedialog.asksaveasfilename(
        title="Save YTT File As",
        defaultextension=".ytt",
        filetypes=[("YouTube TimedText files", "*.ytt"), ("All files", "*.*")],
        initialfile="chat-to-subtitles.ytt"
    )

    if not output_path:
        return

    #get subtitle settings
    comment_font = fontOption.get()
    try: 
        font_size = int(fontSize.get() or "10")
        comment_opacity = opacityOptions.get() / 100
        comment_duration = float(durationOptions.get() or "10")

        if font_size <= 0 or comment_duration <= 0:
            raise ValueError

    except ValueError:
        messagebox.showwarning(
            "Invalid Settings",
            "Please enter a valid font size and comment duration."
        )
        return

    # Assemble the data for the backend in the exact order of sectionList
    ordered_sections = []
    for section in sections:
        json_index = section["jsonIndex"]
        file_path = jsonData[json_index]["path"]
        
        ordered_sections.append({
            "path": file_path,
            "start": section["start"],
            "end": section["end"]
        })

    # Hand the ordered list directly to Berrin's module
    try:
        yttconverter.generate_ytt(ordered_sections, output_path, comment_font=comment_font, font_size=font_size, comment_opacity=comment_opacity, comment_duration=comment_duration)
        messagebox.showinfo("Success", f"YTT file generated successfully!\nSaved to: {output_path}")
    except Exception as error:
        messagebox.showerror("Export Failed", f"An error occurred during conversion:\n{error}")

#--------------------------------------------------------------------------
# Section editor slider functions

# Moves red chatlog timeline markers representing section editor
def rangeMoveMarker(sliderValue, side):
    # Maybe less optimized to init a dictionary every slider move but it looks nice
    offset        = {"left": -11, "right": -1}.get(side, 0)
    rangePlayhead = {"left": rangeMinPlayhead, "right": rangeMaxPlayhead}.get(side, None)

    track_width = timelineMaxx - timelineMinx
    rangeSliderMax = rangeSlider.cget("to")
    sliderPercent = (sliderValue / rangeSliderMax) if rangeSliderMax != 0 else 0
    
    new_x = (timelineMinx + (track_width * sliderPercent) + offset) if sliderPercent != 0 else 40
    current_x = timelines.bbox(rangePlayhead)[0] #why did I write this
    current_y = timelines.bbox(rangePlayhead)[1]

    #print(f"{createSectionRangeSlider.cget("to")} / {sliderPercent} = {new_x}")

    timelines.moveto(rangePlayhead, new_x, current_y)

def rangeUpdateBoxes(hr_box, min_box, sec_box, sliderValue):
    total_sec = max(0, int(sliderValue))
    h, rem = divmod(total_sec, 3600)
    m, s = divmod(rem, 60)
    
    hr_box.delete(0, "end"), hr_box.insert(0, str(h))
    min_box.delete(0, "end"), min_box.insert(0, str(m))
    sec_box.delete(0, "end"), sec_box.insert(0, str(s))

# Initiates changes to the entry boxes
# depending on range slider positions
def rangeSliderDragged(sliderValue, side):
    global lastChatlogMode, chatlogPlayheadValue

    # If in output, activate last used chatlog mode
    if viewerModeButtons.get() == "Full Sections Output":
        viewerModeButtons.set(lastChatlogMode)
        viewerModeSelect(lastChatlogMode)

    #sliderMin, sliderMax = values

    # Move red markers on the main timeline
    #moveRangeMarker(sliderMin, side)
    rangeMoveMarker(sliderValue, side)
    
    chatlogPlayheadValue = sliderValue

    #if(side == "left"):
    #    chatlogPlayheadValue = sliderValue
    #elif(side == "right"):
    #    chatlogPlayheadValue = sliderMax

    #print(chatlogPlayheadValue)

    if currentJson == -1: #or sliderMax == 0:
        return

    if(side == "left"):
        rangeUpdateBoxes(hourStart, minStart, secStart, sliderValue) #update starts
    elif(side == "right"):
        rangeUpdateBoxes(hourEnd, minEnd, secEnd, sliderValue) #update ends

    viewerScroll(sliderValue)
    # def UpdateBoxes(h_box, m_box, s_box, sliderLen):
    #     total_sec = max(0, int(sliderLen))
    #     h, rem = divmod(total_sec, 3600)
    #     m, s = divmod(rem, 60)
        
    #     h_box.delete(0, "end"), h_box.insert(0, str(h))
    #     m_box.delete(0, "end"), m_box.insert(0, str(m))
    #     s_box.delete(0, "end"), s_box.insert(0, str(s))

    # UpdateBoxes(hourStart, minStart, secStart, sliderMin) #update starts
    # UpdateBoxes(hourEnd, minEnd, secEnd, sliderMax) #update ends

    #if sliderMin != rangeSliderValues[0]:
    #    # The left (start) handle moved
    #    if viewerMessageTimes:
    #        ScrollViewer(int(sliderMin))
            
    #elif sliderMax != rangeSliderValues[1]:
    #    # The right (end) handle moved
    #    if viewerMessageTimes:
    #        ScrollViewer(int(sliderMax))

    #rangeSliderValues = (sliderMin, sliderMax)
    
# Entry boxes: make sure they update the
# the positions of the sectioner range handles
def rangeUpdateHandles(event=None):
    # Leave if there is no selected JSON.
    if currentJson == -1:
        return

    try:
        # Get start entries.
        hS = int(hourStart.get() or "0")
        mS = int(minStart.get() or "0")
        sS = float(secStart.get() or "0")

        # Get end entries.
        hE = int(hourEnd.get() or "0")
        mE = int(minEnd.get() or "0")
        sE = float(secEnd.get() or "0")

        # Identify length of current chatlog 
        # and specified points.
        maxEnd = jsonData[currentJson]["endTime"]
        start_sec = helpStampToSec(hS, mS, sS)
        end_sec = helpStampToSec(hE, mE, sE)

        # Ensure start isn't below 0 or above max length.
        start_sec = max(start_sec, 0)
        start_sec = min(start_sec, maxEnd)

        # Ensure end isn't above max.
        end_sec = min(end_sec, maxEnd)

        # Ignore logically invalid entries.
        if start_sec >= end_sec or start_sec < 0:
            return
        
        # Force slider knobs to new positions from entry.
        rangeSlider.set((start_sec, end_sec))
        rangeMoveMarker(start_sec, "left")
        rangeMoveMarker(end_sec, "right")
    except ValueError:
        pass # Ignore incomplete/invalid typing.

#--------------------------------------------------------------------------
# Section timeline slider functions
# Update title string.
def tracksUpdateTitles():
    timelines.itemconfig(timelinesChatlogTitle, text=str(f"Current Source: {int(chatlogPlayheadValue)} Seconds"))
    timelines.itemconfig(timelinesOutputTitle, text=str(f"Full Sections Output: {int(outputPlayheadValue)} Seconds"))  

# Update both timeline playhead lines and number values.
def tracksRefreshPlayheads():
    #print(f"TRP: current json is {currentJson}")
    #print(f"TRP: jsonData len is {len(jsonData)}")
    tracksUpdatePlayhead(timelinesChatlogSlider, chatlogPlayheadLine, jsonLine, chatlogPlayheadText, 
                           (jsonData[currentJson].get('endTime', 0) if currentJson != -1 else 0))
    tracksUpdatePlayhead(timelinesOutputSlider, outputPlayheadLine, yttLine, outputPlayheadText, getYTTDuration())

# Function for updating the position of the slider handle line.
def tracksUpdatePlayhead(slider, tracking_line, base_y, tracking_value, seconds_value):
    #global chatlogPlayheadValue, outputPlayheadValue

    # Calculate percentage of timeline width.
    sliderRange = slider.cget("to") - slider.cget("from_")
    if sliderRange <= 0:
        # No slider? No service. I honestly don't know why I am checking for this.
        # It's to prevent division by zero, but I don't think we'll ever get to this point?
        return

    # Calculate current slider value, turn into seconds.
    sliderPercent = (slider.get() - slider.cget("from_")) / sliderRange
    track_width = timelineMaxx - timelineMinx
    new_x = timelineMinx + (sliderPercent * track_width) + 1
    timelineSeconds = int(seconds_value * sliderPercent)

    # Move tracking line and value around timeline
    timelines.coords(tracking_line, new_x, base_y - 25, new_x, base_y + 15)
    timelines.coords(tracking_value, new_x, base_y - 35)
    timelines.itemconfig(tracking_value, text=str(helpSecToString(timelineSeconds)))

    #if slider is chatlogSlider:
    #    chatlogPlayheadValue = timelineSeconds
    #elif slider is outputSlider:
    #    outputPlayheadValue = timelineSeconds

    # Make sure the line is on top.
    timelines.tag_raise(tracking_line)

    return timelineSeconds

# Helper function for UpdateTimePlayhead, SectionSliderDragged
# directly controls the position of the chat viewer object
def viewerScroll(timelineSeconds):
    # Find the closest message index
    target_index = bisect.bisect_left(viewerTimes, timelineSeconds)

    #print(viewerMessageTimes)

    # Remove highlight from last highlighted message.
    viewer.tag_remove("active_highlight", "1.0", "end")
    
    # Jump to last possible chat message in visualizer
    if target_index >= len(viewerTimes):
        viewer.yview("end")
    else:
        # Create line index usable by viewer
        line_index = f"{target_index + 1}.0"

        # Jump to the found message
        viewer.yview(line_index)

        # Keep track of how close to the end the message is
        timeLeft = len(viewerTimes) - float(line_index)

        # If not near the end, shift the viewer's offset to center the found message more
        if(timeLeft) > 7:
            viewer.yview_scroll(-7, "units")
        else:
            viewer.yview_scroll(-(int(timeLeft)), "units")

        # Highlight the found message
        viewer.tag_add("active_highlight", line_index, f"{line_index} lineend")

#--------------------------------------------------------------------------
# Settings-related helper functions

# For choosing chat viewer modes
def viewerModeSelect(mode):
    global editedOnly, viewerTimes, lastChatlogMode

    # Preview uninterrupted original chatlog
    if mode == "Source Preview":
        lastChatlogMode = mode # Record mode as last selected:
        editedOnly = False
        viewerRenderSource(keep=True)
        viewerScroll(chatlogPlayheadValue)

    # Preview only current chatlog's sections
    elif mode == "Source's Sections Only":
        lastChatlogMode = mode # Record mode as last selected:
        editedOnly = True
        viewerRenderSource(keep=True)
        viewerScroll(chatlogPlayheadValue)

    # Preview output
    elif mode == "Full Sections Output":
        viewerRenderOutput(scrollTo=outputJumppoint)
        viewerScroll(outputPlayheadValue)
    
# Render the current chat row into "small caps" format
# using funny unicode characters
# can't really be covered by simple font changes
def viewerSmallCapsPass(text):
    if settingsSmallCaps:
        lowercase = "abcdefghijklmnopqrstuvwxyz"
        small_caps = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ" 
        caps_map = str.maketrans(lowercase, small_caps)
        return text.translate(caps_map)
    else:
        return text

# Goes to the viewer object and changes its font
# based on what is chosen in settings
def viewerUpdateFont(font):
    global settingsSmallCaps, viewerTimes, outputUseCache

    if fontPreview.get() == 1:
        if(font == "Small Caps"):
            settingsSmallCaps = True
            #print("TRUE")
        else:
            settingsSmallCaps = False

        fontDict = {    # All associated fonts
            "Sans-serif": ("Roboto", 11),
            "Serif": ("Times New Roman", 12),
            "Monospace": ("Lucida Console", 11),
            "Casual": ("Comic Sans MS", 11),
            "Cursive": ("Monotype Corsiva", 14),
            "Small Caps": ("Arial", 11),
            "Defaults": ("Courier New", 11)
        }

        if os.name != 'nt': # Is this not Windows?
            fontDict.update({
                "Sans-serif": ("Helvetica", 11),
                "Monospace": ("Monaco", 10),
                "Cursive": ("Apple Chancery", 13)
            })

        family, size = fontDict.get(font, fontDict["Defaults"])
        viewerFont.configure(family=family, size=size)

        outputUseCache = False
        viewerBuildOutput() #need to rebuild the output to force small caps on/off

        if(viewerModeButtons.get() == "Full Sections Output"):
            viewerTimes = outputTimes # Assign output times list to viewerTimes
            viewerRenderOutput()
            viewerScroll(outputPlayheadValue)
        else:
            viewerRenderSource()
            viewerScroll(chatlogPlayheadValue)
    

# Every time you touch the "PREVIEW FONTS" toggle
# it needs to initiate a few things
# such as resetting the font to Courier New,
# or switching to the just-selected font
def viewerFontReset():
    global settingsSmallCaps, viewerTimes, outputUseCache
    # If set OFF, then reset visualizer to default font.
    if fontPreview.get() == 0:
        #print("TURN OFF FONTS")
        viewerFont.configure(family="Courier New", size=11)
        settingsSmallCaps = False

        outputUseCache = False
        #viewerBuildOutput() #need to rebuild the output to force small caps on/off

        # ONLY FOR IF SWITCHED OFF, clone of this in UpdateViewerFont
        # Rebuild the correct viewer based on active mode
        if viewerModeButtons.get() == "Full Sections Output":
            viewerTimes = outputTimes
            viewerRenderOutput()
            viewerScroll(outputPlayheadValue)
        else:
            viewerRenderSource()
            viewerScroll(chatlogPlayheadValue)

    else:
        viewerUpdateFont(fontOption.get())

#--------------------------------------------------------------------------

def tracksChatlogDragged():
    global chatlogPlayheadValue

    #Reassign chatlogPlayheadValue for the sake of updating the playhead objects.
    endTime = jsonData[currentJson].get('endTime', 0) if currentJson != -1 else 0
    chatlogPlayheadValue = tracksUpdatePlayhead(timelinesChatlogSlider, chatlogPlayheadLine, jsonLine, chatlogPlayheadText, endTime)

    # Update timeline titles.
    tracksUpdateTitles()

    # Return to last used non-output chatlog viewer.
    if viewerModeButtons.get() == "Full Sections Output":
        #print(lastChatlogMode)
        viewerModeButtons.set(lastChatlogMode)
        viewerModeSelect(lastChatlogMode)

    # If ANY messages exist IN THE VIEWER, 
    # scroll to playhead value. Should match chatlog slider at this point.
    if viewerTimes:
        viewerScroll(chatlogPlayheadValue)

def tracksOutputDragged():
    global outputPlayheadValue, outputJumppoint

    #Reassign outputPlayheadValue for the sake of updating the playhead objects.
    outputPlayheadValue = tracksUpdatePlayhead(timelinesOutputSlider, outputPlayheadLine, yttLine, outputPlayheadText, getYTTDuration())
    outputJumppoint = "playhead" # switching modes will emphasize playhead

    # Update timeline titles.
    tracksUpdateTitles()
    
    if viewerModeButtons.get() != "Full Sections Output":
        viewerModeButtons.set("Full Sections Output")
        viewerModeSelect("Full Sections Output")

    # If ANY messages exist IN THE VIEWER, 
    # scroll to playhead value. Should match output slider at this point.
    if viewerTimes:
        viewerScroll(outputPlayheadValue)

#--------------------------------------------------------------------------
#----------------------------- INITIALIZE UI ------------------------------
#--------------------------------------------------------------------------
#Defining general App sections. leftSide, sectionEditor
app.grid_rowconfigure(0, weight=0)
app.grid_rowconfigure(1, weight=1)
app.grid_columnconfigure(1, weight=1)

leftSide = customtkinter.CTkFrame(master=app, width=200)
leftSide.grid(row=0, column=0, rowspan=2, padx=10, pady=10, sticky="nsew")
leftSide.grid_propagate(False)

rangeBox = customtkinter.CTkFrame(master=app)
rangeBox.grid(row=0, column=1, padx=10, pady=10, sticky="new")

rightSide = customtkinter.CTkFrame(master=app, width=275)
rightSide.grid(row=0, column=2, rowspan=2, padx=10, pady=10, sticky="nsew")
rightSide.grid_propagate(False)

#--------------------------------------------------------------------------
# leftSide. Importing and JSON visualizer.
# leftSide = customtkinter.CTkFrame(master=app)
# leftSide.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
leftSide.grid_columnconfigure(0, weight=1)
leftSide.grid_rowconfigure(2, weight=1)

# importJSON. Prompts user to import JSON files.
importJSON = customtkinter.CTkButton(master=leftSide, text="Import by File", font = ("Roboto", 13), command=importJSON)
importJSON.grid(row=0, column=0, padx=5, pady=5, sticky="new")

# importURL. Prompts user to enter a URL to download directly from a Twitch VOD link.
importDownloadURL = customtkinter.CTkButton(master=leftSide, text="Import by URL", font = ("Roboto", 13), command=importDownloadURL, fg_color="#7a2b2b", hover_color="#5c1e1e")
importDownloadURL.grid(row=1, column=0, padx=5, pady=5, sticky="new")

# Contains list of all the chatlogs
# Change: renamed this to "shelf" because visualizer too confusingly similar to viewer
jsonShelf = customtkinter.CTkScrollableFrame(master=leftSide)
jsonShelf.grid_columnconfigure(0, weight=1)
jsonShelf.grid_rowconfigure(1, weight=1)
jsonShelfTitle = customtkinter.CTkLabel(master = jsonShelf, text="Imported Sources") # renamed to "Sources" for consistency
jsonShelfTitle.grid(row=0, column=0, padx=1, pady=(1, 10), sticky="ew")
jsonShelfTitle.configure(font = ("Roboto", 15))
jsonShelf.grid(row=2, column=0, rowspan=2, padx=5, pady=5, sticky="nsew")

#--------------------------------------------------------------------------
#rightSide. Export and section editor.
#rightSide = customtkinter.CTkFrame(master=app)
#rightSide.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
rightSide.grid_columnconfigure(0, weight=1)
rightSide.grid_rowconfigure(2, weight=1)

#exportButton. Sends the ordered list of JSONs to the YTT subtitles converter.
exportButton = customtkinter.CTkButton(master=rightSide, text="Export to YTT", font = ("Roboto", 13), command=exportYTT, fg_color="#2b7a3d", hover_color="#1e5c2d")
exportButton.grid(row=0, column=0, padx=5, pady=5, sticky="new")

#settingsButton. doesn't do anything yet
# TODO: make this do anything lol
# intended to make a popup
settingsButton = customtkinter.CTkButton(master=rightSide, text="Settings", font = ("Roboto", 14), fg_color="#7a5e2b", hover_color="#5c481e")
settingsButton.grid(row=1, column=0, padx=5, pady=5, sticky="new")

#sectionShelf. Where the user reorganizes the order of JSON sections.
# Change: renamed this to "shelf" to match json list on the left
sectionShelf = customtkinter.CTkScrollableFrame(master=rightSide)
sectionShelf.grid(row=2, column=0, rowspan=1, padx=10, pady=(10, 0), sticky="nsew")

sectionShelf.grid_columnconfigure(0, weight=1)
sectionShelf.grid_rowconfigure(1, weight=1)

sectionShelfTitle = customtkinter.CTkLabel(master = sectionShelf, text=f"Section Editor")
sectionShelfTitle.grid(row=0, column=0, padx=0, pady=(1, 1), sticky="ew")
sectionShelfTitle.configure(font = ("Roboto", 15))

sectionTotalTime = customtkinter.CTkLabel(master = sectionShelfTitle, text=f"Total Time: {helpSecToString(getYTTDuration())}")
sectionTotalTime.grid_rowconfigure(1, weight=0)
sectionTotalTime.grid(row=1, column=0, padx=0, pady=0, sticky="ew")

#sectionShifterButtons. Section shift and delete buttons
sectionShifterButtons = customtkinter.CTkFrame(master=rightSide)
sectionShifterButtons.grid(row=3, column=0, padx=10, pady=(2, 10), sticky="ew")
sectionShifterButtons.grid_rowconfigure(0, weight=1)

shiftUpButton = customtkinter.CTkButton(master=sectionShifterButtons, text="▲", font = ("Roboto", 18), command=callUp, width=40)
shiftUpButton.grid(row=0, column=0, padx=(65, 3), pady=5, sticky="ns")
shiftDownButton = customtkinter.CTkButton(master=sectionShifterButtons, text="▼", font = ("Roboto", 18), command=callDown, width=40)
shiftDownButton.grid(row=0, column=1, padx=3, pady=5, sticky="ns")
shiftDownButton = customtkinter.CTkButton(master=sectionShifterButtons, text="⌫", font = ("Roboto", 14), command=callDelete, width=40)
shiftDownButton.grid(row=0, column=2, padx=3, pady=5, sticky="ns")

#----------------------------------------------------------------------------------------------
#subtitle settings
settingsBox = customtkinter.CTkFrame(master=rightSide)
settingsBox.grid(row=5, column=0, padx=10, pady=(0, 10), sticky="ew")
settingsBox.grid_columnconfigure(1, weight=1)

settingsTitle = customtkinter.CTkLabel(master=settingsBox, text="Subtitle Settings", font=("Roboto", 11))
settingsTitle.grid(row=0, column=0, columnspan=2, padx=15, pady=(4, 2), sticky="w")

#font and size options
fontPreview = customtkinter.CTkSwitch(master=settingsBox, text="Preview Font", command=viewerFontReset)
fontPreview.grid(row=0, column=1, padx=20, pady=2, sticky="e")

customtkinter.CTkLabel(master=settingsBox, text="Font:").grid(row=1, column=0, padx=(8, 4), pady=2, sticky="e")
fontOption = customtkinter.CTkOptionMenu(master=settingsBox, values=["Sans-serif", "Serif", "Monospace", "Casual", "Cursive", "Small Caps"], height=24, command=viewerUpdateFont)
fontOption.grid(row=1, column=1, padx=(0, 8), pady=2, sticky="ew")
fontOption.set("Sans-serif")

customtkinter.CTkLabel(master=settingsBox, text="Size:").grid(row=2, column=0, padx=(8, 4), pady=2, sticky="e")
fontSize = customtkinter.CTkEntry(master=settingsBox, placeholder_text="10", height=24)
fontSize.insert(0, "10")
fontSize.grid(row=2, column=1, padx=(0, 8), pady=2, sticky="ew")

#duration and opacity options
customtkinter.CTkLabel(master=settingsBox, text="Opacity:").grid(row=3, column=0, padx=(8, 4), pady=2, sticky="e")
opacityOptions = customtkinter.CTkSlider(master=settingsBox, from_=0, to=100, number_of_steps=100, height=14)
opacityOptions.set(100)
opacityOptions.grid(row=3, column=1, padx=(0, 8), pady=2, sticky="ew")

customtkinter.CTkLabel(master=settingsBox, text="Wait:").grid(row=4, column=0, padx=(8, 4), pady=(2, 6), sticky="e")
durationOptions = customtkinter.CTkEntry(master=settingsBox, placeholder_text="10", height=24)
durationOptions.insert(0, "10")
durationOptions.grid(row=4, column=1, padx=(0, 8), pady=(2, 6), sticky="ew")

#--------------------------------------------------------------------------
#rangeBox. Where the user adds a new JSON section to the sectionEditor.
#Change: sectionAdder to rangeBox
rangeBox.grid_columnconfigure(0, weight=1)
rangeBox.grid_propagate(False)

rangeTitle = customtkinter.CTkLabel(master = rangeBox, text="Create Subtitle Section")
rangeTitle.grid(row=0, column=0, padx=0, pady=(5, 0), sticky="nsew")
rangeTitle.configure(font = ("Roboto", 15))

rangeSourceTitle = customtkinter.CTkLabel(master = rangeBox, text="No Chatlog Selected")
rangeSourceTitle.grid(row=1, column=0, padx=1, pady=(5, 1), sticky="ew")

timeEntry = customtkinter.CTkFrame(master=rangeBox)
timeEntry.grid(row=2, column=0, padx=1, pady=1, sticky="n")
timeEntry.grid_columnconfigure(0, weight=1)
timeEntry.grid_rowconfigure(0, weight=1)

hourStart = customtkinter.CTkEntry(timeEntry, placeholder_text="h")
hourStart.grid(row=0, column=0, padx=(5, 0), pady=5, sticky="n")
hourStart.configure(width=30, justify="center")
hmsColon = customtkinter.CTkLabel(master = timeEntry, text=":")
hmsColon.grid(row=0, column=1, padx=(2, 2.1), pady=5)
minStart = customtkinter.CTkEntry(timeEntry, placeholder_text="m")
minStart.grid(row=0, column=2, pady=5, sticky="n")
minStart.configure(width=30, justify="center")
mssColon = customtkinter.CTkLabel(master = timeEntry, text=":")
mssColon.grid(row=0, column=3, padx=(2, 2.1), pady=5)
secStart = customtkinter.CTkEntry(timeEntry, placeholder_text="s")
secStart.grid(row=0, column=4, pady=5, sticky="n")
secStart.configure(width=30, justify="center")

hyphen = customtkinter.CTkLabel(master = timeEntry, text="-")
hyphen.grid(row=0, column=5, padx=(10,10.5), pady=5)

hourEnd = customtkinter.CTkEntry(timeEntry, placeholder_text="h")
hourEnd.grid(row=0, column=6, pady=5, sticky="n")
hourEnd.configure(width=30, justify="center")
hmeColon = customtkinter.CTkLabel(master = timeEntry, text=":")
hmeColon.grid(row=0, column=7, padx=(2, 2.1), pady=5)
minEnd = customtkinter.CTkEntry(timeEntry, placeholder_text="m")
minEnd.grid(row=0, column=8, pady=5, sticky="n")
minEnd.configure(width=30, justify="center")
mseColon = customtkinter.CTkLabel(master = timeEntry, text=":")
mseColon.grid(row=0, column=9, padx=(2, 2.1), pady=5)
secEnd = customtkinter.CTkEntry(timeEntry, placeholder_text="s")
secEnd.grid(row=0, column=10, padx=(0, 5), pady=5, sticky="n")
secEnd.configure(width=30, justify="center")

rangeSlider = CTkRangeSlider(master=rangeBox, from_=0, to=100, width=900, progress_color="#785F65", button_color="#9e0800", button_hover_color="#610500", command=(lambda values: rangeSliderDragged(values, "left"), lambda values: rangeSliderDragged(values, "right")))
rangeSlider.grid(row=3, column=0, padx=5, pady=2, sticky="ew")

rangeCreateButton = customtkinter.CTkButton(master=rangeBox, text="Create Section", command=sectionCreateNormal)
rangeCreateButton.grid(row=4, column=0, padx=5, pady=(5,3), sticky="n")

emptyCreator = customtkinter.CTkFrame(master=rangeBox)
emptyCreator.grid(row=5, column=0, padx=1, pady=1, sticky="n")
emptyCreator.grid_rowconfigure(0, weight=1)

hourEmpty = customtkinter.CTkEntry(emptyCreator, placeholder_text="h")
hourEmpty.grid(row=0, column=0, padx=(5, 0), pady=5, sticky="n")
hourEmpty.configure(width=30, justify="center")
hmemColon = customtkinter.CTkLabel(master = emptyCreator, text=":")
hmemColon.grid(row=0, column=1, padx=(2, 2.1), pady=5)
minEmpty = customtkinter.CTkEntry(emptyCreator, placeholder_text="m")
minEmpty.grid(row=0, column=2, pady=5, sticky="n")
minEmpty.configure(width=30, justify="center")
msemColon = customtkinter.CTkLabel(master = emptyCreator, text=":")
msemColon.grid(row=0, column=3, padx=(2, 2.1), pady=5)
secEmpty = customtkinter.CTkEntry(emptyCreator, placeholder_text="s")
secEmpty.grid(row=0, column=4, pady=5, sticky="n")
secEmpty.configure(width=30, justify="center")

rangeEmptyButton = customtkinter.CTkButton(master=emptyCreator, text="Create Spacer", command=sectionCreateEmpty)
rangeEmptyButton.grid(row=0, column=5, padx=5, pady=5)

#--------------------------------------------------------------------------
#Middle Section Scroller. The chatlog viewer. Its scrollbar is its own and is NOT connected to any slider as of right now.
viewerFrame = customtkinter.CTkFrame(master=app)
viewerFrame.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="nsew")
viewerFrame.grid_columnconfigure(0, weight=1)
viewerFrame.grid_rowconfigure(1, weight=1)

viewerFrame.grid_propagate(False)
viewerFrame.grid_columnconfigure(0, weight=1)
viewerFrame.grid_rowconfigure(1, weight=1)

#editedOnlyButton = customtkinter.CTkButton(master=viewerFrame, text="Show only sections", command=ToggleEditedOnly)
#editedOnlyButton.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

viewerModeButtons = customtkinter.CTkSegmentedButton(master=viewerFrame, values=["Source Preview", "Source's Sections Only", "Full Sections Output"], command=viewerModeSelect)
viewerModeButtons.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky="ew")
viewerModeButtons.grid_propagate(False)
viewerModeButtons.set("Source Preview")

viewerTimeFont = tkfont.Font(family="Courier New", size=11) #This doesn't change: font for the timecodes.
viewerFont = tkfont.Font(family="Courier New", size=11) #Monospace so the timestamp column lines up

#The text box is created first, so the scrollbar can be connected to it directly.
viewer = tkinter.Text(
    viewerFrame,
    height=1,
    width=1,
    wrap="word",
    font=viewerFont,
    bg="#202020",
    fg="#ffffff",
    borderwidth=0,
    highlightthickness=0,
    padx=8,
    pady=6,
    state="disabled"
)
viewer.grid(row=1, column=0, padx=(5, 0), pady=(0, 5), sticky="nsew")
viewer.grid_propagate(False)

viewerScrollbar = customtkinter.CTkScrollbar(master=viewerFrame, orientation="vertical", command=viewer.yview)
viewerScrollbar.grid(row=1, column=1, padx=(0, 5), pady=(0, 5), sticky="ns")
viewer.configure(yscrollcommand=viewerScrollbar.set)

# Define tag definitions. Short for optimization reasons?
# Tag for time in seconds.
viewer.tag_config("timestamp", foreground="#6fa8dc", font=viewerTimeFont)
# Tag for messages outside of any section.
viewer.tag_config("out", foreground="#8a8a8a")
# Tag for messages long enough to be hanging.
viewer.tag_config("hang", lmargin2=viewerFont.measure("0") * (outputStampWidth + 2))
# Tag for section start labels.
viewer.tag_config("st")
# Tag for highlighted messages under scroll
viewer.tag_config("active_highlight", background="#0a0a0a")
viewer.tag_config("header", foreground="#ffffff", font=viewerTimeFont)

#--------------------------------------------------------------------------
#Timelines. Where the currently selected JSON's timeline is displayed, and where the total YTT section view is displayed.
timelines = tkinter.Canvas(
    app,
    width=1000,
    height=300,
    bg="#202020", #Matching canvas with customtkinter color
    highlightthickness=0
)
timelines.grid(row=4, column=0, columnspan=3)

# Build the base timeline graphics at start of runtime (?)
timelines.create_line(timelineMinx, jsonLine, timelineMaxx, jsonLine, fill="white")
timelines.create_line(timelineMinx, jsonLine + timelineMark + 5, timelineMinx, jsonLine - timelineMark - 5, fill="white")
timelines.create_line(timelineMaxx, jsonLine + timelineMark + 5, timelineMaxx, jsonLine - timelineMark - 5, fill="white")

timelines.create_line(timelineMinx, yttLine, timelineMaxx, yttLine, fill="white")
timelines.create_line(timelineMinx, yttLine + timelineMark + 5, timelineMinx, yttLine - timelineMark - 5, fill="white")
timelines.create_line(timelineMaxx, yttLine + timelineMark + 5, timelineMaxx, yttLine - timelineMark - 5, fill="white")

leftHandTriangle = [(40, 100),      # Top vertex
                   (50, 90),        # Bottom right vertex
                   (40, 80)]        # Bottom left vertex

rightHandTriangle = [(960, 100),    # Top vertex
                   (950, 90),       # Bottom right vertex
                   (960, 80)]       # Bottom left vertex

rangeMinPlayhead = timelines.create_polygon(leftHandTriangle, fill="#e91515", outline="#382E2E", width=0)
rangeMaxPlayhead = timelines.create_polygon(rightHandTriangle, fill="#e91515", outline="#382E2E", width=0)

# Add line + time value tracked with chatlog slider handle.
chatlogPlayheadLine = timelines.create_line(50, jsonLine - 25, 50, jsonLine + 15, fill="#1f538d", width=2)
chatlogPlayheadText = timelines.create_text(50, 55, text="00:00:00", fill="white")
timelines.tag_raise(chatlogPlayheadLine)

# Add line + time value tracked with output slider handle.
outputPlayheadLine = timelines.create_line(50, yttLine - 25, 50, yttLine + 15, fill="#2b7a3d", width=2)
outputPlayheadText = timelines.create_text(50, 205, text="00:00:00", fill="white")
timelines.tag_raise(outputPlayheadLine)

# Timeline Titles
timelinesChatlogTitle = timelines.create_text(500, jsonLine - 55,
    text=f"Current Source: {int(chatlogPlayheadValue)}", 
    fill="white", font=("Roboto", 13), anchor="center")

timelinesOutputTitle = timelines.create_text(500, yttLine - 55,
    text=f"Full Sections Output: {int(outputPlayheadValue)}",
    fill="white", font=("Roboto", 13), anchor="center")

# Slider object for the chatlog timeline.
timelinesChatlogSlider = customtkinter.CTkSlider(
    master=timelines, from_=0, to=100, width=916,
    fg_color = "#202020",
    bg_color="transparent", progress_color="transparent",
    command=lambda val: tracksChatlogDragged())

timelinesChatlogSlider.place(x=43, y=102), timelinesChatlogSlider.set(0)

# Slider object for the output timeline.
timelinesOutputSlider = customtkinter.CTkSlider(
    master=timelines, from_=0, to=100, width=916,
    fg_color = "#202020",
    bg_color="transparent", progress_color="transparent",
    button_color="#2b7a3d", button_hover_color="#1e5c2d",
    command=lambda val: tracksOutputDragged()
)
timelinesOutputSlider.place(x=43, y=252), timelinesOutputSlider.set(0)

#--------------------------------------------------------------------------
# Timeline Management

def tracksRedraw():
    global viewerTimes, outputTimes, outputUseCache
    outputUseCache = False
    timelines.delete("sections")

    duration = getYTTDuration()
    starts = getSectionStarts()
    timelineLength = timelineMaxx - timelineMinx

    # Rebuild output cache whenever sections change
    #viewerBuildOutput()

    if(duration > 0):
        #print(f"AAAGHHGH {duration}")
        timelinesOutputSlider.configure(to=duration)
        timelinesOutputSlider.set(outputPlayheadValue)
    
    i = 0
    for section in sections:
        if section["jsonIndex"] == currentJson:
            jsonLength = jsonData[currentJson]["endTime"]
            jsonxS = (section["start"]/jsonLength * timelineLength) + timelineMinx + 1
            jsonxE = (section["end"]/jsonLength * timelineLength) + timelineMinx - 1
            timelines.create_line(jsonxS, jsonLine + timelineMark, jsonxS, jsonLine - timelineMark, fill=section["color"], tags="sections")
            timelines.create_line(jsonxE, jsonLine + timelineMark, jsonxE, jsonLine - timelineMark, fill=section["color"], tags="sections")
            timelines.create_line(jsonxS, jsonLine - timelineMark, jsonxE, jsonLine - timelineMark, fill=section["color"], tags="sections")

        yttxS = ((starts[i]/duration) * timelineLength) + timelineMinx + 1
        yttxE = (((starts[i+1])/duration) * timelineLength) + timelineMinx - 1
        timelines.create_line(yttxS, yttLine + timelineMark, yttxS, yttLine - timelineMark, fill=section["color"], tags="sections")
        timelines.create_line(yttxE, yttLine + timelineMark, yttxE, yttLine - timelineMark, fill=section["color"], tags="sections")
        timelines.create_line(yttxS, yttLine - timelineMark, yttxE, yttLine - timelineMark, fill=section["color"], tags="sections")
        i += 1

    # Keep the slider tracking lines on top!
    timelines.tag_raise(chatlogPlayheadLine)
    timelines.tag_raise(outputPlayheadLine)

    tracksUpdateTitles()
    tracksRefreshPlayheads()

    # Update displayed time.
    sectionTotalTime.configure(text=f"Total Time: {helpSecToString(getYTTDuration())}")

'''    if viewerModeButtons.get() == "Full Sections Output":
        viewerTimes = outputTimes
        viewerRenderOutput(keep=keep, scroll=scroll) # Refresh viewer if currently in output mode
    else:
        #print(f"tracksRedraw scroll = {scroll}")
        viewerRenderSource(keep=keep, scroll=scroll)  #Refresh the viewer whenever sections are created, deleted or reordered.'''

def viewerRenderAgnostic(keep=False, scroll=True, scrollTo="top"):
    if viewerModeButtons.get() == "Full Sections Output":
        viewerRenderOutput(scrollTo=scrollTo) # Refresh viewer if currently in output mode
    else:
        #print(f"tracksRedraw scroll = {scroll}")
        viewerRenderSource(keep=keep, scroll=scroll)  #Refresh the viewer whenever sections are created, deleted or reordered.


#Things to do when the app starts
importEmptyJSON()

#--------------------------------------------------------------------------
# Keyboard Input
def KeyPress(event): #No switch statement cus I don't want to mess with python versions
    global currentSection, viewerSection
    if event.keysym == "Up":
        if currentSection > 0:
            sectionSwap(currentSection, currentSection - 1)
    elif event.keysym == "Down":
        if currentSection < len(sections) - 1:
            sectionSwap(currentSection, currentSection + 1)
    elif event.keysym == "Delete":
        if not isinstance(app.focus_get(), customtkinter.CTkEntry):
            sectionDelete(currentSection)  # Let the entry handle Delete normally
            
app.bind("<KeyPress>", KeyPress)

# Entry box keybinds:
# Makes sure that typing in the section entry boxes
# is reflected in the range slider.
hourStart.bind("<KeyRelease>", rangeUpdateHandles)
minStart.bind("<KeyRelease>", rangeUpdateHandles)
secStart.bind("<KeyRelease>", rangeUpdateHandles)
hourEnd.bind("<KeyRelease>", rangeUpdateHandles)
minEnd.bind("<KeyRelease>", rangeUpdateHandles)
secEnd.bind("<KeyRelease>", rangeUpdateHandles)

#--------------------------------------------------------------------------
# Cleanup
# Manually delete the tempfiles... Not entirely sure if this is necessary.
def cleanup():
    for file_path in tempDownloads:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"Cleaned up temp file: {file_path}")
            except Exception as e:
                print(f"Could not remove {file_path}: {e}")

atexit.register(cleanup)
tracksRedraw()

#--------------------------------------------------------------------------
app.mainloop()  # Called at the end.
