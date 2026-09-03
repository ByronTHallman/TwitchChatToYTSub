#!/usr/bin/python3 

import sys
import json
import datetime
import secrets
import html


# Name file should be in command line
if len(sys.argv) < 2:
	print("You need to add the input json as an argument.")
	exit()


with open(sys.argv[1], 'r', encoding='UTF8') as jsonFile:
	data = json.loads(jsonFile.read())

# Time delay in second for chat, to sync with video. For me, 7s looks like it's in sync with what the video display
delta = 7
# Duration of display of the line
duration = 10
# Size of the font. Supposed to be in percent of standart, but it looks like all sizes aren't available
size = 10
# Bacground color. The standart of YT is solid black
background_color = "#000000"
# Opacity of the background color. Between 0 and 254. 254 means that the color is not transparent
background_opacity = 200
header = '<?xml version="1.0" encoding="utf-8"?><timedtext format="3"><head><wp id="0" ap="7" ah="0" av="0" /><wp id="1" ap="6" ah="0" av="100" /><ws id="0" ju="2" pd="0" sd="0" /><ws id="1" ju="0" pd="0" sd="0" />'
middle = '</head><body>'
footer = '</body></timedtext>'
spacer = '<s p="1">​\n​</s>'

output = ''
texts = []
timestamps = []
colors = ["#000000", "#FEFEFE"]
users = ["yt-bug", "white-text"]
for i in data['comments']:
	display_name = i['commenter']['display_name']
	message = i['message']['body']
	
	if display_name not in users:
		users.append(display_name)
		userIndex = users.index(display_name)

		if i['message']['user_color'] is not None:
			color = i['message']['user_color']
		else:
			color = "#"+secrets.token_hex(3)
			#print(display_name+color)
		
		colors.insert(userIndex, color)
	else:
		userIndex = users.index(display_name)

	texts.append('<s p="'+str(userIndex)+'">'+display_name+':</s><s p="1"> '+html.escape(message)+'</s>')
	timestamps.append([i['content_offset_seconds']+delta, True])
	timestamps.append([i['content_offset_seconds']+delta+duration, False])


lengthColors = len(colors)
for i in range(lengthColors):
	header += '<pen id="'+str(i)+'" sz="'+str(size)+'" fc="'+colors[i]+'" fo="254" bc="'+background_color+'" bo="'+str(background_opacity)+'" />'

timestamps.sort(key=lambda x: x[0])

start = 0
end = 1
length = len(timestamps)
for i in range(1,length):
	combined_text = ""
	for j in range(start,end):
		combined_text += texts[j]
		if j != end-1:
			combined_text += spacer
			
	timestamp_start = int(timestamps[i-1][0]*1000)
	timestamp_end = int(timestamps[i][0]*1000)
	
	if start != end:
		output += '<p t="'+str(timestamp_start)+'" d="'+str(timestamp_end-timestamp_start)+'" wp="1" ws="1"><s p="1">​</s>'+combined_text+'<s p="1">​</s></p>'

	if timestamps[i][1]:
		end += 1
	else:
		start += 1


if len(sys.argv) == 3:
	with open(sys.argv[2], 'w', encoding='UTF8') as outputFile:
		outputFile.write(header+middle+output+footer)
else:
	print(header+middle+output+footer)
