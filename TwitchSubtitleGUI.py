import atexit
import tempfile
import os # for handling download management
from CTkRangeSlider import *
import customtkinter
import tkinter
import json
import random
import threading # important for downloading
from datetime import datetime, timedelta # importing time and date to get downloaded vod dates from first message.
import yttconverter
import chat_downloader
from chat_downloader import ChatDownloader
from tkinter import filedialog, messagebox
from pathlib import Path

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
app.title("where even am i")
app.focus_force()

# Universal global variables
jsonData = [] #List of dictionaries. "path", "name", "endTime"
currentJson = -1 #The index of the current JSON in jsonData
sectionList = [] #List of dictionaries. "json", "start", "end", "button", "ogIndex", "color", ""
currentSection = -1 #The index of the current section in sectionList
colors = [ #Some hand-picked OKLCH colors
    "#973c5d", "#964601", "#4c6c01", "#04733a",
    "#007078", "#0164a3", "#5c52a3", "#824387"
]
lastColor = "#000000" #The last used color so we don't use it again

# Timeline and specific numeric global variables.
timelineMinx = 50 # The lefthand side of the timelines.
timelineMaxx = 950 # The righthand side of the timelines.
timelineMark = 8 # The delta y values of each mark on the timeline
jsonLine = 90 # The y values of the current chatlog timeline.
yttLine = 240 # The y values of the output timeline.
chatlogPlayheadValue = 0 # Global variable storing first timeline playhead value for access.
outputPlayheadValue = 0 #Global variable storing second timeline playhead value for access.

# Tempfile global variables
tempDownloads = [] #Any file downloaded by URL will be added to this list to be removed on shutdown
tempDir = tempfile.gettempdir()

#--------------------------------------------------------------------------
#Functions
#Opens JSON file picker, imports, and adds data to jsonData
def ImportJSON():

    # Create a placeholder "Importing..." card
    # Doing this before the filedialog process because
    # the filedialog process seems to take the longest.
    jsonCard = customtkinter.CTkButton(
        master=jsonVisualizer,
        text="Importing...",
        state="disabled",   # Prevent clicking while loading
        fg_color="#374c64"  # Greyer color for loading state
    )
    jsonCard.grid(row=len(jsonData)+1, column=0, padx=5, pady=2, sticky="ew")

    # Prompt user for JSON.
    filePath = filedialog.askopenfilename(
        title="Import JSON file",
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
    )
    if not filePath:
        app.after(0, jsonCard.destroy) # Remove the "importing..." card.
        return

    # Attempt import of JSON file.
    try:
        with open(filePath, "r", encoding="utf-8") as json_file:
            imported_data = json.load(json_file)
    except (OSError, json.JSONDecodeError) as error:
        messagebox.showerror("Import failed", f"Could not load this JSON file:\n{error}")
        app.after(0, jsonCard.destroy)
        return

    # Get stream metadata to create label.
    json_metadata = ImportMetadataJSON(imported_data)

    # Label information.
    json_label = f"{json_metadata['streamer']}, {json_metadata['date']}\nGame: {json_metadata['game']}"
    duration = json_metadata.get('duration', 0)

    # Warn the user if the chatlog is devoid of comments, but let them use it if they want to for some ungodly reason.
    if json_metadata.get('comments') == []:
        json_label += "\nWARNING: EMPTY"
        app.after(0, messagebox.showwarning("Import Warning", f"No messages found for this file."))

    # If some data is missing, fallback to filename.
    if(not (json_metadata['streamer'] or json_metadata['game'] or json_metadata['date'])):
        json_label = Path(filePath).stem

    # Attach this JSON to the chain of chatlog information.
    jsonData.append({"path":filePath, "name":json_label, "endTime":duration})
    if len(jsonData) == 1:
        SelectJson(0)

    # Update the "importing" label to reflect the JSON's information.
    jsonCard.configure(
        text=str(len(jsonData)-1) 
        + " - " + jsonData[-1]["name"] 
        + "\nDuration: "
        + "(" 
        + str(timedelta(seconds=duration)) + ")",
        state="normal",
        fg_color="#1f538d", hover_color="#14375e",
        command=lambda index=len(jsonData) - 1: SelectJson(index)
    )

# This works now. Make sure to build with
# this specific build of chat-downloader.
# pip install git+https://github.com/Indigo128/chat-downloader.git@all_current_fixes
def ImportURL():

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
    # Will be updated after successful download.
    urlCard = customtkinter.CTkButton(
        master=jsonVisualizer,
        text="Downloading...",
        state="disabled",   # Prevent clicking while loading
        fg_color="#644040"  # Greyer color for loading state
    )
    urlCard.grid(row=len(jsonData)+1, column=0, padx=5, pady=2, sticky="ew")

    # Inner function for downloading via ChatDownloader library.
    def download():
        # Attempt to download directly via user's URL, trying to format to match previous style.
        try:
            # Download chat.
            vod_chat = ChatDownloader().get_chat(vod_url)

            # Raw username links lock up Chat Downloader.
            # Don't let them do that.
            if getattr(vod_chat, 'status', '') in ['live', 'upcoming']:
                raise NonMediaError()
            
            # Check the first message and store it, 
            # otherwise lost due to how generator objects 
            # like "chat_downloader.sites.common.Chat" work.
            try:
                first_message = next(vod_chat)
            except StopIteration:
                raise EmptyChatError()

            # Get metadata for label information.
            vod_metadata = QueryMetadataVOD(vod_chat, first_message)
            vod_label = CreateLabel(vod_metadata, vod_chat)
            vod_duration = vod_metadata.get('duration', 0)

            # Create tempfile for storing the downloaded JSON with a relevant ID.
            vod_id = WriteID(vod_url)
            vod_tempfile = str(Path(tempDir) / f"temp_chat_{vod_id}.json")
            tempDownloads.append(vod_tempfile)

            # Parse comments into expected format for converter.
            formatted_comments = [CommentFormatter(first_message)]
            for vod_message in vod_chat:
                formatted_comments.append(CommentFormatter(vod_message))

            # Dump formatted comments into downloaded temp file.
            with open(vod_tempfile, "w", encoding="utf-8") as f:
                json.dump({"comments": formatted_comments}, f, ensure_ascii=False, indent=4)

        # Exceptions and warnings for invalid URLs:
        except NonMediaError as error:
            app.after(0, urlCard.destroy)
            app.after(0, lambda: messagebox.showwarning("Import Failed", f"Please enter a VOD or Clip URL, not a channel link."))
            return

        # Warn the user if the downloaded VOD has no comments. Unfortunate, but it does happen sometimes.
        except EmptyChatError as error:
            app.after(0, urlCard.destroy)
            app.after(0, lambda: messagebox.showwarning("Import Failed", f"No messages found for this VOD:\n{vod_url}"))
            return

        # Other errors.
        except Exception as error:
            app.after(0, urlCard.destroy)
            app.after(0, lambda: messagebox.showerror("Import Failed for Unknown Reasons", f"Could not fetch chat from URL:\n{vod_url}"))
            return

        # If successful download, attach VOD info to the chain of chatlog information.
        def update_ui():
            jsonData.append({"path": vod_tempfile, "name": vod_label, "endTime": vod_duration, "comments": formatted_comments})
            if len(jsonData) == 1:
                SelectJson(0)

            # Update the "downloading" label to reflect the VOD's information
            urlCard.configure(
                text=str(len(jsonData)-1) 
                + " - " + jsonData[-1]["name"] 
                + "\nDuration: " 
                + "(" 
                + str(timedelta(seconds=vod_duration)) + ")",
                state="normal",
                fg_color="#7a2b2b", hover_color="#5c1e1e",
                command=lambda index=len(jsonData) - 1: SelectJson(index)
            )

        # Needed due to threading.
        app.after(0, update_ui)

    #Program froze on download unless threading was brought in.
    threading.Thread(target=download, daemon=True).start()

#--------------------------------------------------------------------------
# CHATLOG / SECTION MANAGEMENT

def SelectJson(index):
    global currentJson
    currentJson = index
    currentChatlogText.configure(
        text="Current Chatlog: " + jsonData[currentJson]["name"]
    )

    endTime = jsonData[currentJson]["endTime"]
    createSectionRangeSlider.configure(to=endTime)
    createSectionRangeSlider.set((0, endTime)) # Reset knobs to start and end
    
    # Force text boxes to match the new reset slider
    SectionSliderDragged([0, endTime])
    return

def CreateSection():
    if currentJson == -1:
        return
    try:
        hourS = int(hourStart.get() or "0") #or "0" for when text entry is left empty
        minS = int(minStart.get() or "0")
        secS = float(secStart.get() or "0")
        hourE = int(hourEnd.get() or "0")
        minE = int(minEnd.get() or "0")
        secE = float(secEnd.get() or "0")

    except ValueError:
        messagebox.showwarning("Invalid Input", "Please enter valid numbers for the timestamp.")
        return

    start = StampToSec(hourS,minS,secS)
    end = StampToSec(hourE,minE,secE)
    maxEnd = jsonData[currentJson]["endTime"]

    #Update endpoint depending on validity of inputs.
    end = ValidateEnd(start, end, maxEnd)
    if(end == 0):
        return

    color = GenerateColor()
    sectionButton = customtkinter.CTkButton(
        master=sectionEditor,
        text=str(len(sectionList)) + " - " + jsonData[currentJson]["name"] + "\n" + SecToString(start) + " - " + SecToString(end),
        command=lambda index=len(sectionList): SelectSection(index)
    )
    sectionButton.configure(fg_color = color, hover = False)
    sectionList.append({"json":currentJson, "start":start, "end":end, "button":sectionButton, "ogIndex":len(sectionList), "color":color, "jsonIndex":currentJson})
    sectionButton.grid(row=len(sectionList), column=0, padx=5, pady=5, sticky="nsew")
    SelectSection(len(sectionList))
    RedrawTimelines()
    return

def SelectSection(index):
    global currentSection
    currentSection = index
    return

def SwapSections(index1, index2):
    global sectionList
    sectionList[index1]["button"].configure(command=lambda index=index2: SelectSection(index)) #swapping lamda commands
    sectionList[index2]["button"].configure(command=lambda index=index1: SelectSection(index))
    sectionList[index1]["button"].grid(row=index2 + 1) #swapping location in sectionEditor
    sectionList[index2]["button"].grid(row=index1 + 1)
    sectionList[index1], sectionList[index2] = sectionList[index2], sectionList[index1] #swapping sectionList elements using tuple unpacking
    return

def DeleteSection(index):
    global sectionList
    for i in range(index, len(sectionList)-1): #From index to second last index
        SwapSections(i, i+1)
    sectionList[-1]["button"].destroy()
    sectionList.pop(index)
    RedrawTimelines()
    return

# Ensures section colors aren't repeated in sequence.
def GenerateColor():
    global lastColor
    color = random.choice(colors)
    while color == lastColor:
        color = random.choice(colors)
    lastColor = color
    return color

# Checks whether the section timestamps make sense, and updates the end accordingly.
# Seems to be a less friction-inducing implementation.
def ValidateEnd(start, end, maxEnd): 
    if(maxEnd) <= 0 or (start >= maxEnd):
        messagebox.showwarning("Invalid Section", "Specified time can only create section of zero seconds, please try again.")
        return 0
    if(end > maxEnd):
        messagebox.showwarning("Section Warning", "Specified time longer than chatlog.\n\nSetting end to maximum length.")
        return maxEnd
    if start > end or start < 0 or end < 0:
        messagebox.showwarning("Section Warning", "Please make sure your start is not before your end.\n\nSetting end to maximum length.")
        return maxEnd
    elif start == end:
        messagebox.showwarning("Section Warning", "Section is zero seconds long!\n\nSetting end to maximum length.")
        return maxEnd

    # Leave end unchanged if valid.
    return end

#--------------------------------------------------------------------------
# Parsing helper functions

def StampToSec(hours, minutes, seconds):
    sec = hours * 3600 + minutes * 60 + seconds
    return sec

def SecToString(seconds):
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
def CommentFormatter(comment):
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
def CreateLabel(metadata, vod_chat):
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

#--------------------------------------------------------------------------
# Global timing info helper functions

# Returns the total time elapsed in the output file.
def YTTDuration():
    totalTime = 0
    for section in sectionList:
        totalTime += section["end"] - section["start"] #+ 1 I don't really understand this +1 so removing it, very sorry #times are inclusive so I'm adding 1
    return totalTime

# Returns a list of all the starting times of the sections relative to each cumulative addition.
def SectionStarts():
    totalTime = 0
    starts = []
    for section in sectionList:
        starts.append(totalTime)
        totalTime += section["end"] - section["start"] #+ 1 I don't really undestand this +1 so removing it, very sorry #times are inclusive so I'm adding 1
    starts.append(totalTime)
    return starts

#--------------------------------------------------------------------------
# Import/download-related helper functions

# For tempfile management, extracts VOD ID for use as a backend label.
def WriteID(vod_url):
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
def QueryMetadataVOD(vod_chat, first_message):

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
def ImportMetadataJSON(imported_data, json_comments = []):

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
    json_lastsec = json_lastmsg.get("content_offset_seconds", json_lastmsg.get("time_in_seconds", 0))
    json_duration = json_video_data.get('end', 0) if json_video_data else json_lastsec

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
def ExportYTT():
    if len(sectionList) == 0:
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
        
    # Assemble the data for the backend in the exact order of sectionList
    ordered_sections = []
    for section in sectionList:
        json_index = section["json"]
        file_path = jsonData[json_index]["path"]
        
        ordered_sections.append({
            "path": file_path,
            "start": section["start"],
            "end": section["end"]
        })

    # Hand the ordered list directly to Berrin's module
    try:
        yttconverter.generate_ytt(ordered_sections, output_path)
        messagebox.showinfo("Success", f"YTT file generated successfully!\nSaved to: {output_path}")
    except Exception as error:
        messagebox.showerror("Export Failed", f"An error occurred during conversion:\n{error}")

#--------------------------------------------------------------------------
# Section editor slider functions

def SectionSliderDragged(values):
    sliderMin, sliderMax = values

    if currentJson == -1 or sliderMax == 0:
        return
            
    def UpdateBoxes(h_box, m_box, s_box, sliderLen):
        total_sec = max(0, int(sliderLen))
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        
        h_box.delete(0, "end"), h_box.insert(0, str(h))
        m_box.delete(0, "end"), m_box.insert(0, str(m))
        s_box.delete(0, "end"), s_box.insert(0, str(s))

    UpdateBoxes(hourStart, minStart, secStart, sliderMin) #update starts
    UpdateBoxes(hourEnd, minEnd, secEnd, sliderMax) #update ends

def UpdateSectionHandles(event=None):
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
        start_sec = StampToSec(hS, mS, sS)
        end_sec = StampToSec(hE, mE, sE)

        # Ensure start isn't below 0 or above max length.
        start_sec = max(start_sec, 0)
        start_sec = min(start_sec, maxEnd)

        # Ensure end isn't above max.
        end_sec = min(end_sec, maxEnd)

        # Ignore logically invalid entries.
        if start_sec >= end_sec or start_sec < 0:
            return
        
        # Force slider knobs to new positions from entry.
        createSectionRangeSlider.set((start_sec, end_sec))
    except ValueError:
        pass # Ignore incomplete/invalid typing.

#--------------------------------------------------------------------------
# Section timeline slider functions

# Update title string.
def UpdateTimelineTitles():
    timelines.itemconfig(chatlogTimelineTitle, text=str(f"Current Chatlog: {chatlogPlayheadValue}"))
    timelines.itemconfig(outputTimelineTitle, text=str(f"Output File: {outputPlayheadValue}"))  

# Quickly update both timeline playhead lines and number values.
def RefreshTimelinePlayheads():
    UpdateTimelinePlayhead(chatlogSlider, chatlogPlayheadLine, jsonLine, chatlogPlayheadText, 
                           (jsonData[currentJson].get('endTime', 0) if currentJson != -1 else 0))
    UpdateTimelinePlayhead(outputSlider, outputPlayheadLine, yttLine, outputPlayheadText, YTTDuration())

# Function for updating the position of the slider handle line.
def UpdateTimelinePlayhead(slider, tracking_line, base_y, tracking_value, seconds_value):
    global chatlogPlayheadValue, outputPlayheadValue

    # Calculate percentage of timeline width.
    sliderRange = slider.cget("to") - slider.cget("from_")
    if sliderRange <= 0:
        # No slider? No service. I honestly don't know why I am checking for this.
        # It's to prevent division by zero, but I don't think we'll ever get to this point.
        return

    # Calculate current slider value, turn into seconds.
    sliderPercent = (slider.get() - slider.cget("from_")) / sliderRange
    track_width = timelineMaxx - timelineMinx
    new_x = timelineMinx + (sliderPercent * track_width) + 1
    timelineSeconds = int(seconds_value * sliderPercent)

    # Move tracking line and value around timeline
    timelines.coords(tracking_line, new_x, base_y - 25, new_x, base_y + 15)
    timelines.coords(tracking_value, new_x, base_y - 35)
    timelines.itemconfig(tracking_value, text=str(SecToString(timelineSeconds)))

    # Update label variable.
    UpdateTimelineTitles()                                          

    if slider is chatlogSlider:
        chatlogPlayheadValue = timelineSeconds
    elif slider is outputSlider:
        outputPlayheadValue = timelineSeconds

    # Make sure the line is on top.
    timelines.tag_raise(tracking_line)

#--------------------------------------------------------------------------
#----------------------------- INITIALIZE UI ------------------------------
#--------------------------------------------------------------------------
#Defining general App sections. leftSide, sectionEditor
app.grid_rowconfigure(0, weight=1)
app.grid_columnconfigure(1, weight=1)
leftSide = customtkinter.CTkFrame(master=app)
leftSide.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

sectionAdder = customtkinter.CTkFrame(master=app)
sectionAdder.grid(row=0, column=1, padx=10, pady=10, sticky="new")

rightSide = customtkinter.CTkFrame(master=app)
rightSide.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")

#--------------------------------------------------------------------------
# leftSide. Importing and JSON visualizer.
leftSide = customtkinter.CTkFrame(master=app)
leftSide.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
leftSide.grid_columnconfigure(0, weight=1)
leftSide.grid_rowconfigure(2, weight=1)

# importJSON. Prompts user to import JSON files.
importJSON = customtkinter.CTkButton(master=leftSide, text="Import by File", command=ImportJSON)
importJSON.grid(row=0, column=0, padx=5, pady=5, sticky="new")

# importURL. Prompts user to enter a URL to download directly from a Twitch VOD link.
importURL = customtkinter.CTkButton(master=leftSide, text="Import by URL", command=ImportURL, fg_color="#7a2b2b", hover_color="#5c1e1e")
importURL.grid(row=1, column=0, padx=5, pady=5, sticky="new")

# Contains list of all the chatlogs.
jsonVisualizer = customtkinter.CTkScrollableFrame(master=leftSide)
jsonVisualizer.grid_columnconfigure(0, weight=1)
jsonVisualizer.grid_rowconfigure(1, weight=1)
jsonVisualizerTitle = customtkinter.CTkLabel(master = jsonVisualizer, text="Imported Chatlogs")
jsonVisualizerTitle.grid(row=0, column=0, padx=1, pady=(1, 10), sticky="ew")
jsonVisualizerTitle.configure(font = ("Roboto", 15))
jsonVisualizer.grid(row=2, column=0, padx=5, pady=5, sticky="nsew")

#--------------------------------------------------------------------------
#rightSide. Export and section editor.
rightSide = customtkinter.CTkFrame(master=app)
rightSide.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
rightSide.grid_columnconfigure(0, weight=1)
rightSide.grid_rowconfigure(1, weight=1)

#exportButton. Sends the ordered list of JSONs to the YTT subtitles converter.
exportButton = customtkinter.CTkButton(master=rightSide, text="Export to YTT", command=ExportYTT, fg_color="#2b7a3d", hover_color="#1e5c2d")
exportButton.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

#sectionEditor. Where the user reorganizes the order of JSON sections.
sectionEditor = customtkinter.CTkScrollableFrame(master=rightSide)
sectionEditor.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

sectionEditor.grid_columnconfigure(0, weight=1)
sectionEditor.grid_rowconfigure(1, weight=1)

sectionEditorTitle = customtkinter.CTkLabel(master = sectionEditor, text=f"Section Editor")
sectionEditorTitle.grid(row=0, column=0, padx=0, pady=(1, 1), sticky="ew")
sectionEditorTitle.configure(font = ("Roboto", 15))

sectionTotalTime = customtkinter.CTkLabel(master = sectionEditorTitle, text=f"Total Time: {SecToString(YTTDuration())}")
sectionTotalTime.grid_rowconfigure(1, weight=0)
sectionTotalTime.grid(row=1, column=0, padx=0, pady=0, sticky="ew")

#--------------------------------------------------------------------------
#sectionAdder. Where the user adds a new JSON section to the sectionEditor.
sectionAdder.grid_columnconfigure(0, weight=1)
sectionAdder.grid_rowconfigure(4, weight=1)

sectionAdderTitle = customtkinter.CTkLabel(master = sectionAdder, text="Create Subtitle Section")
sectionAdderTitle.grid(row=0, column=0, padx=1, pady=(5, 0), sticky="ew")
sectionAdderTitle.configure(font = ("Roboto", 15))

currentChatlogText = customtkinter.CTkLabel(master = sectionAdder, text="No Chatlog Selected")
currentChatlogText.grid(row=1, column=0, padx=1, pady=(5, 1), sticky="ew")

timeEntry = customtkinter.CTkFrame(master=sectionAdder)
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

createSectionRangeSlider = CTkRangeSlider(master=sectionAdder, from_=0, to=100, width=900, command=SectionSliderDragged)
createSectionRangeSlider.grid(row=3, column=0, padx=5, pady=2, sticky="ew")

createSectionButton = customtkinter.CTkButton(master=sectionAdder, text="Create Section", command=CreateSection)
createSectionButton.grid(row=4, column=0, padx=5, pady=(10,15), sticky="n")

#--------------------------------------------------------------------------
#Timelines. Where the currently selected JSON's timeline is displayed, and where the total YTT section view is displayed.
timelines = tkinter.Canvas(
    app,
    width=400,
    height=300,
    bg="#202020", #Matching canvas with customtkinter color
    highlightthickness=0
)
timelines.grid(row=4, column=0, columnspan=3, sticky="nsew")

# Add line + time value tracked with chatlog slider handle.
chatlogPlayheadLine = timelines.create_line(50, jsonLine - 25, 50, jsonLine + 15, fill="#1f538d", width=2)
chatlogPlayheadText = timelines.create_text(50, 55, text="00:00:00", fill="white")
timelines.tag_raise(chatlogPlayheadLine)

# Add line + time value tracked with output slider handle.
outputPlayheadLine = timelines.create_line(50, yttLine - 25, 50, yttLine + 15, fill="#2b7a3d", width=2)
outputPlayheadText = timelines.create_text(50, 205, text="00:00:00", fill="white")
timelines.tag_raise(outputPlayheadLine)

# Timeline Titles
chatlogTimelineTitle = timelines.create_text(500, jsonLine - 55,
    text=f"Current Chatlog: {chatlogPlayheadValue}", 
    fill="white", font=("Roboto", 13), anchor="center")

outputTimelineTitle = timelines.create_text(500, yttLine - 55,
    text=f"Output File: {outputPlayheadValue}",
    fill="white", font=("Roboto", 13), anchor="center")

# Slider object for the chatlog timeline.
chatlogSlider = customtkinter.CTkSlider(
    master=timelines, from_=0, to=100, width=916,
    fg_color = "#202020",
    bg_color="transparent", progress_color="transparent",
    command=lambda val: UpdateTimelinePlayhead(chatlogSlider, chatlogPlayheadLine, jsonLine, chatlogPlayheadText, (jsonData[currentJson].get('endTime', 0) if currentJson != -1 else 0))
)
chatlogSlider.place(x=43, y=102), chatlogSlider.set(0)

# Slider object for the output timeline.
outputSlider = customtkinter.CTkSlider(
    master=timelines, from_=0, to=100, width=916,
    fg_color = "#202020",
    bg_color="transparent", progress_color="transparent",
    button_color="#2b7a3d", button_hover_color="#1e5c2d",
    command=lambda val: UpdateTimelinePlayhead(outputSlider, outputPlayheadLine, yttLine, outputPlayheadText, YTTDuration())
)
outputSlider.place(x=43, y=252), outputSlider.set(0)

#--------------------------------------------------------------------------
# Timeline Management

def RedrawTimelines():
    timelines.delete("sections")

    timelines.create_line(timelineMinx, jsonLine, timelineMaxx, jsonLine, fill="white")
    timelines.create_line(timelineMinx, jsonLine + timelineMark + 5, timelineMinx, jsonLine - timelineMark - 5, fill="white")
    timelines.create_line(timelineMaxx, jsonLine + timelineMark + 5, timelineMaxx, jsonLine - timelineMark - 5, fill="white")

    timelines.create_line(timelineMinx, yttLine, timelineMaxx, yttLine, fill="white")
    timelines.create_line(timelineMinx, yttLine + timelineMark + 5, timelineMinx, yttLine - timelineMark - 5, fill="white")
    timelines.create_line(timelineMaxx, yttLine + timelineMark + 5, timelineMaxx, yttLine - timelineMark - 5, fill="white")

    duration = YTTDuration()
    starts = SectionStarts()
    timelineLength = timelineMaxx - timelineMinx
    
    i = 0
    for section in sectionList:
        if section["json"] == currentJson:
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

    UpdateTimelineTitles()
    RefreshTimelinePlayheads()

    # Update displayed time.
    sectionTotalTime.configure(text=f"Total Time: {SecToString(YTTDuration())}")
    return


#--------------------------------------------------------------------------
# Keyboard Input
def KeyPress(event): #No switch statement cus I don't want to mess with python versions
    global currentSection
    if event.keysym == "Up":
        if currentSection > 0:
            SwapSections(currentSection, currentSection - 1)
            currentSection = currentSection - 1
            RedrawTimelines()
    elif event.keysym == "Down":
        if currentSection < len(sectionList) - 1:
            SwapSections(currentSection, currentSection + 1)
            currentSection = currentSection + 1
            RedrawTimelines()
    elif event.keysym == "Delete":
        if isinstance(app.focus_get(), customtkinter.CTkEntry):
            return  # Let the entry handle Delete normally
        else:
            DeleteSection(currentSection)
app.bind("<KeyPress>", KeyPress)

# Entry box keybinds:
# Makes sure that typing in the section entry boxes
# is reflected in the range slider.
hourStart.bind("<KeyRelease>", UpdateSectionHandles)
minStart.bind("<KeyRelease>", UpdateSectionHandles)
secStart.bind("<KeyRelease>", UpdateSectionHandles)
hourEnd.bind("<KeyRelease>", UpdateSectionHandles)
minEnd.bind("<KeyRelease>", UpdateSectionHandles)
secEnd.bind("<KeyRelease>", UpdateSectionHandles)

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
RedrawTimelines()

#--------------------------------------------------------------------------
app.mainloop()  # Called at the end.
