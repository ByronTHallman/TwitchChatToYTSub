import customtkinter
import tkinter
import json
import random
from tkinter import filedialog, messagebox
from pathlib import Path

#--------------------------------------------------------------------------
#Startup Stuff
customtkinter.set_appearance_mode("dark")
customtkinter.set_default_color_theme("dark-blue")

app = customtkinter.CTk()  # creates the window
app.geometry("1000x800")
app.resizable(False, False) #The timelines sorta break if the window is resizable.
app.title("idk bro")

jsonData = [] #List of dictionaries. "path", "name", "endTime"
currentJson = -1 #The index of the current JSON in jsonData
sectionList = [] #List of dictionaries. "json", "start", "end", "button", "ogIndex", "color"
currentSection = -1 #The index of the current section in sectionList
colors = [ #Some hand-picked OKLCH colors
    "#973c5d", "#964601", "#4c6c01", "#04733a",
    "#007078", "#0164a3", "#5c52a3", "#824387"
]
lastColor = "#000000" #The last used color so we don't use it again

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
def ImportJson():
    filePath = filedialog.askopenfilename(
        title="Import JSON file",
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
    )
    if not filePath:
        return

    try:
        with open(filePath, "r", encoding="utf-8") as json_file:
            imported_data = json.load(json_file)
    except (OSError, json.JSONDecodeError) as error:
        messagebox.showerror("Import failed", f"Could not load this JSON file:\n{error}")
        return

    lastSecond = imported_data["comments"][-1]["content_offset_seconds"]
    fileName = Path(filePath).stem
    jsonData.append({"path":filePath, "name":fileName, "endTime":lastSecond})
    if len(jsonData) == 1:
        SelectJson(0)
    newCard = customtkinter.CTkButton(
        master=jsonVisualizer,
        text=str(len(jsonData)-1) + " - " + jsonData[-1]["name"] + "\nDuration: " + str(jsonData[-1]["endTime"]),
        command=lambda index=len(jsonData) - 1: SelectJson(index)
    )
    newCard.grid(row=len(jsonData), column=0, padx=5, pady=2, sticky="ew")

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

    if not ValidTime(start, end):
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

def ValidTime(start, end): #Checks whether the section timestamps are valid. Returns False if invalid, True if valid.
    if start >= end or start < 0 or end < 0 or end > jsonData[currentJson]["endTime"]:
        return False
    else:
        return True

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
        630, jsonLine - 55,
        text="Current Chatlog",
        fill="white",
        font=("Roboto", 13),
        anchor="center"
    )
    timelines.create_text(
        630, yttLine - 55,
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

#--------------------------------------------------------------------------
#Defining general App sections. leftSide, sectionEditor
app.grid_rowconfigure(0, weight=1)
app.grid_columnconfigure(1, weight=1)
leftSide = customtkinter.CTkFrame(master=app)
leftSide.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

sectionEditor = customtkinter.CTkScrollableFrame(master=app)
sectionEditor.grid(row=0, column=2, padx=10, pady=10, sticky="nsew")

sectionAdder = customtkinter.CTkFrame(master=app)
sectionAdder.grid(row=0, column=1, padx=10, pady=10, sticky="new")

#--------------------------------------------------------------------------
#leftSide. Importing and JSON visualizer.
leftSide = customtkinter.CTkFrame(master=app)
leftSide.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
leftSide.grid_columnconfigure(0, weight=1)
leftSide.grid_rowconfigure(1, weight=1)

importButton = customtkinter.CTkButton(master=leftSide, text="Import Chatlog", command=ImportJson)
importButton.grid(row=0, column=0, padx=5, pady=5, sticky="new")

jsonVisualizer = customtkinter.CTkScrollableFrame(master=leftSide)
jsonVisualizer.grid_columnconfigure(0, weight=1)
jsonVisualizer.grid_rowconfigure(1, weight=1)
jsonVisualizerTitle = customtkinter.CTkLabel(master = jsonVisualizer, text="Imported Chatlogs")
jsonVisualizerTitle.grid(row=0, column=0, padx=1, pady=(1, 10), sticky="ew")
jsonVisualizerTitle.configure(font = ("Roboto", 15))
jsonVisualizer.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

#--------------------------------------------------------------------------
#sectionEditor. Where the user reorganizes the order of JSON sections.
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
timelineMaxx = 1200
timelineMark = 8 #The delta y values of each mark on the timeline
jsonLine = 90 #The y values of each timelined
yttLine = 240

RedrawTimelines()

#--------------------------------------------------------------------------
app.mainloop()  # Called at the end.
