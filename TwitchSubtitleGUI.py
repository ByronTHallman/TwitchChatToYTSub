import atexit
import tempfile
import os #for handling download management
import customtkinter
import tkinter
import json
import random
import threading
#Kai Change 11/5/26: Importing time and date to get downloaded vod dates from first message.
from datetime import datetime, timedelta
#Kai Change 10/31/26: New imports needed for merging.
import yttconverter
import chat_downloader
from chat_downloader import ChatDownloader
from tkinter import filedialog, messagebox
from pathlib import Path

#--------------------------------------------------------------------------
#Startup Stuff
customtkinter.set_appearance_mode("dark")
customtkinter.set_default_color_theme("dark-blue")

app = customtkinter.CTk()  # creates the window
app.geometry("1000x800")
app.resizable(False, False) #The timelines sorta break if the window is resizable.
app.title("where even am i")

jsonData = [] #List of dictionaries. "path", "name", "endTime"
currentJson = -1 #The index of the current JSON in jsonData
sectionList = [] #List of dictionaries. "json", "start", "end", "button", "ogIndex", "color"
currentSection = -1 #The index of the current section in sectionList
colors = [ #Some hand-picked OKLCH colors
    "#973c5d", "#964601", "#4c6c01", "#04733a",
    "#007078", "#0164a3", "#5c52a3", "#824387"
]
lastColor = "#000000" #The last used color so we don't use it again
tempDownloads = [] #Any file downloaded by URL will be added to this list to be removed on shutdown
tempDir = tempfile.gettempdir()

#--------------------------------------------------------------------------
#Keyboard Input
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
        app.after(0, jsonCard.destroy)
        return

    # Attempt importing.
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
    lastSecond = (json_metadata['comments'][-1].get("content_offset_seconds", 0) or json_metadata['comments'][-1].get("time_in_seconds")) if json_metadata['comments'] else 0

    # If some data is missing, fallback to filename.
    if(not (json_metadata['streamer'] or json_metadata['game'] or json_metadata['date'])):
        json_label = Path(filePath).stem

    # Attach this JSON to the chain of chatlog information.
    jsonData.append({"path":filePath, "name":json_label, "endTime":lastSecond})
    if len(jsonData) == 1:
        SelectJson(0)

    # Update the "importing" label to reflect the JSON's information.
    jsonCard.configure(
        text=str(len(jsonData)-1) 
        + " - " + jsonData[-1]["name"] 
        + "\nDuration: "
        + "(" 
        + str(timedelta(seconds=lastSecond)) + ")",
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
            # Need to query metadata for more streamer name, game name.
            vod_chat = ChatDownloader().get_chat(vod_url)

            # Chat Downloader locks up if we let users input just links to Twitch profile pages.
            # Don't let them do that.
            if getattr(vod_chat, 'status', '') in ['live', 'upcoming']:
                messagebox.showwarning("Invalid URL", "Please enter a VOD or Clip URL, not a channel link.")
                app.after(0, urlCard.destroy)
                return

            # Get metadata for label information.
            vod_metadata = QueryMetadataVOD(vod_chat, vod_url)
            vod_label = CreateLabel(vod_metadata, vod_chat)

            # Write an appropriate ID value to the current VOD.
            vod_id = WriteID(vod_url)

            # Create tempfile for storing the downloaded JSON.
            vod_tempfile = str(Path(tempDir) / f"temp_chat_{vod_id}.json")
            tempDownloads.append(vod_tempfile)

            # Parse comments into expected format for converter.
            formatted_comments = []
            for vod_message in vod_chat:
                formatted_comment = {
                    'commenter': {
                            'display_name': vod_message.get('author', {}).get('display_name', '')
                    },
                    'message': {
                            'body': vod_message.get('message', ''),
                            'user_color': vod_message.get('author', {}).get('colour')
                    },
                    'content_offset_seconds': vod_message.get('time_in_seconds', 0.0)
                }
                formatted_comments.append(formatted_comment)
            lastSecond = formatted_comments[-1]["content_offset_seconds"] if formatted_comments else 0.0

            # Dump formatted comments into downloaded temp file.
            with open(vod_tempfile, "w", encoding="utf-8") as f:
                json.dump({"comments": formatted_comments}, f, ensure_ascii=False, indent=4)

        # Exceptions and warnings for invalid URLs:
        except Exception as error:
            # I'll be honest, I'm not sure why formatting it this way is necessary,
            # aside from the fact that threading causes the exception to break without this variable.
            err_msg = str(error)
            app.after(0, urlCard.destroy)
            app.after(0, lambda url=err_msg: messagebox.showerror("Import failed", f"Could not fetch chat from URL:\n{url}"))
            return

        # Warn the user if the downloaded VOD has no comments. Unfortunate, but it does happen sometimes.
        if not formatted_comments:
            app.after(0, lambda: messagebox.showwarning("Empty Chat", "Warning: No messages found for this VOD."))

        # If successful download, attach VOD info to the chain of chatlog information.
        def update_ui():
            jsonData.append({"path": vod_tempfile, "name": vod_label, "endTime": lastSecond, "comments": formatted_comments})
            if len(jsonData) == 1:
                SelectJson(0)

            # Update the "downloading" label to reflect the VOD's information
            urlCard.configure(
                text=str(len(jsonData)-1) 
                + " - " + jsonData[-1]["name"] 
                + "\nDuration: " 
                + "(" 
                + str(timedelta(seconds=lastSecond)) + ")",
                state="normal",
                fg_color="#7a2b2b", hover_color="#5c1e1e",
                command=lambda index=len(jsonData) - 1: SelectJson(index)
            )

        # Needed due to threading.
        app.after(0, update_ui)

    #Program froze on download unless threading was brought in.
    threading.Thread(target=download, daemon=True).start()

def SelectJson(index):
    global currentJson
    currentJson = index
    currentChatlogText.configure(
        text="Current Chatlog: " + jsonData[currentJson]["name"]
    )
    return

def CreateSection():
    if currentJson == -1:
        return

    hourS = int(hourStart.get() or "0") #or "0" for when text entry is left empty
    minS = int(minStart.get() or "0")
    secS = int(secStart.get() or "0")
    hourE = int(hourEnd.get() or "0")
    minE = int(minEnd.get() or "0")
    secE = int(secEnd.get() or "0")

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
    sectionList.append({"json":currentJson, "start":start, "end":end, "button":sectionButton, "ogIndex":len(sectionList), "color":color})
    sectionButton.grid(row=len(sectionList), column=0, padx=5, pady=5, sticky="nsew")
    SelectSection(len(sectionList))
    RedrawTimelines()
    return

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
# Returns a dictionary to parse for the label.
def QueryMetadataVOD(vod_chat, vod_url):

    # Run query for metadata.
    vod_query = [{'operationName': 'VideoMetadata', 'variables': {'channelLogin': '', 'videoID': vod_chat.id}}]
    vod_data = vod_chat.site._download_gql(vod_query)[0]['data']['video']

    # Create label for "Imported Chatlogs" UI.
    streamer = vod_data.get('owner', {}).get('displayName') if vod_data else "Unknown"
    game = vod_data.get('game', {}).get('displayName') if vod_data and vod_data.get('game') else "Unknown Game"
    utc = next(iter(vod_chat))['timestamp'] if vod_chat else 0
    date = datetime.fromtimestamp(utc / 1000000).strftime(f"%m/%d/%y")

    # Clips struggle to provide information, so we'll force it to be this.
    media_type = getattr(vod_chat, 'video_type', 'unknown')
    if media_type == "clip":
        streamer = 'Clip'
        game = 'Clip'

    # Return as metadata dictionary.
    return {
        "streamer": streamer,
        "game": game,
        "date": date
    }

# Parses the imported JSON file to find information
# like streamer name, game name.
# If those can't be found, handle it accordingly.
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

    # Create label.
    json_streamer = json_streamer_data.get('name') if json_streamer_data else 'Unknown'
    json_game = json_chapter_data[0].get('gameDisplayName') if json_chapter_data and len(json_chapter_data) > 0 else 'Unknown Game'
    json_date = f"{month}/{day}/{year[-2:]}" if json_date_data != None else 'Unknown Date'

    # Return as metadata dictionary, along with "comments" to be parsed for time.
    return{
        'streamer': json_streamer,
        'game': json_game,
        'date': json_date,
        'comments': json_comments
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

def StampToSec(hours, minutes, seconds):
    sec = hours * 3600 + minutes * 60 + seconds
    return sec

def SecToString(seconds):
    hours = seconds // 3600
    seconds = seconds % 3600
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def YTTDuration():
    totalTime = 0
    for section in sectionList:
        totalTime += section["end"] - section["start"] + 1 #times are inclusive so I'm adding 1
    return totalTime

def SectionStarts():
    totalTime = 0
    starts = []
    for section in sectionList:
        starts.append(totalTime)
        totalTime += section["end"] - section["start"] + 1 #times are inclusive so I'm adding 1
    starts.append(totalTime)
    return starts

def RedrawTimelines():
    timelines.delete("all")

    timelines.create_line(timelineMinx, jsonLine, timelineMaxx, jsonLine, fill="white")
    timelines.create_line(timelineMinx, yttLine, timelineMaxx, yttLine, fill="white")
    timelines.create_line(timelineMinx, jsonLine + timelineMark + 5, timelineMinx, jsonLine - timelineMark - 5, fill="white")
    timelines.create_line(timelineMaxx, jsonLine + timelineMark + 5, timelineMaxx, jsonLine - timelineMark - 5, fill="white")
    timelines.create_line(timelineMinx, yttLine + timelineMark + 5, timelineMinx, yttLine - timelineMark - 5, fill="white")
    timelines.create_line(timelineMaxx, yttLine + timelineMark + 5, timelineMaxx, yttLine - timelineMark - 5, fill="white")

    duration = YTTDuration()
    starts = SectionStarts()
    timelineLength = timelineMaxx - timelineMinx

    timelines.create_text(
        #Kai Change 10/30/26: Changed 630 to 500 for X-coordinate.
        500, jsonLine - 55,
        text="Current Chatlog",
        fill="white",
        font=("Roboto", 13),
        anchor="center"
    )
    timelines.create_text(
        #Kai Change 10/30/26: Changed 630 to 500 for X-coordinate.
        500, yttLine - 55,
        text="Output File",
        fill="white",
        font=("Roboto", 13),
        anchor="center"
    )

    i = 0
    for section in sectionList:
        if section["json"] == currentJson:
            jsonLength = jsonData[currentJson]["endTime"]
            jsonxS = (section["start"]/jsonLength * timelineLength) + timelineMinx + 1
            jsonxE = (section["end"]/jsonLength * timelineLength) + timelineMinx - 1
            timelines.create_line(jsonxS, jsonLine + timelineMark, jsonxS, jsonLine - timelineMark, fill=section["color"])
            timelines.create_line(jsonxE, jsonLine + timelineMark, jsonxE, jsonLine - timelineMark, fill=section["color"])
            timelines.create_line(jsonxS, jsonLine - timelineMark, jsonxE, jsonLine - timelineMark, fill=section["color"])

        yttxS = ((starts[i]/duration) * timelineLength) + timelineMinx + 1
        yttxE = (((starts[i+1])/duration) * timelineLength) + timelineMinx - 1
        timelines.create_line(yttxS, yttLine + timelineMark, yttxS, yttLine - timelineMark, fill=section["color"])
        timelines.create_line(yttxE, yttLine + timelineMark, yttxE, yttLine - timelineMark, fill=section["color"])
        timelines.create_line(yttxS, yttLine - timelineMark, yttxE, yttLine - timelineMark, fill=section["color"])
        i += 1
    return

def GenerateColor():
    global lastColor
    color = random.choice(colors)
    while color == lastColor:
        color = random.choice(colors)
    lastColor = color
    return color

#Kai Change 10/29/26: The primary merging implementation, sends data to Berrin's converter and executes it. 
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
#leftSide. Importing and JSON visualizer.
leftSide = customtkinter.CTkFrame(master=app)
leftSide.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
leftSide.grid_columnconfigure(0, weight=1)
leftSide.grid_rowconfigure(2, weight=1)

#importJSON. Prompts user to import JSON files.
importJSON = customtkinter.CTkButton(master=leftSide, text="Import by File", command=ImportJSON)
importJSON.grid(row=0, column=0, padx=5, pady=5, sticky="new")

importURL = customtkinter.CTkButton(master=leftSide, text="Import by URL", command=ImportURL, fg_color="#7a2b2b", hover_color="#5c1e1e")
importURL.grid(row=1, column=0, padx=5, pady=5, sticky="new")

jsonVisualizer = customtkinter.CTkScrollableFrame(master=leftSide)
jsonVisualizer.grid_columnconfigure(0, weight=1)
jsonVisualizer.grid_rowconfigure(1, weight=1)
jsonVisualizerTitle = customtkinter.CTkLabel(master = jsonVisualizer, text="Imported Chatlogs")
jsonVisualizerTitle.grid(row=0, column=0, padx=1, pady=(1, 10), sticky="ew")
jsonVisualizerTitle.configure(font = ("Roboto", 15))
jsonVisualizer.grid(row=2, column=0, padx=5, pady=5, sticky="nsew")

#--------------------------------------------------------------------------
#Kai Change 10/29/26: Created right side master to mirror left side of UI, seemed to look nice.
#rightSide. Export and section editor.
rightSide = customtkinter.CTkFrame(master=app)
rightSide.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")
rightSide.grid_columnconfigure(0, weight=1)
rightSide.grid_rowconfigure(1, weight=1)

#Kai Change 10/29/26: Needed to add this for obvious reasons.
#exportButton. Sends the ordered list of JSONs to the YTT subtitles converter.
exportButton = customtkinter.CTkButton(master=rightSide, text="Export to YTT", command=ExportYTT, fg_color="#2b7a3d", hover_color="#1e5c2d")
exportButton.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

#sectionEditor. Where the user reorganizes the order of JSON sections.
sectionEditor = customtkinter.CTkScrollableFrame(master=rightSide)
sectionEditor.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

sectionEditor.grid_columnconfigure(0, weight=1)
sectionEditor.grid_rowconfigure(1, weight=1)

sectionEditorTitle = customtkinter.CTkLabel(master = sectionEditor, text="Section Editor")
sectionEditorTitle.grid(row=0, column=0, padx=1, pady=(1, 10), sticky="ew")
sectionEditorTitle.configure(font = ("Roboto", 15))

#--------------------------------------------------------------------------
#sectionAdder. Where the user adds a new JSON section to the sectionEditor.
sectionAdder.grid_columnconfigure(0, weight=1)
sectionAdder.grid_rowconfigure(3, weight=1)

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

createSectionButton = customtkinter.CTkButton(master=sectionAdder, text="Create Section", command=CreateSection)
createSectionButton.grid(row=3, column=0, padx=5, pady=(10,15), sticky="n")

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
timelineMinx = 50
#Kai Change 10/30/26: Old Y Coord as timelineMaxx = 1200 went off screen.
timelineMaxx = 950
timelineMark = 8 #The delta y values of each mark on the timeline
jsonLine = 90 #The y values of each timelined
yttLine = 240

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
