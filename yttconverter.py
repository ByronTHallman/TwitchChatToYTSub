#!/usr/bin/python3 

import sys
import json
import secrets
import html

#Kai Change 10/28/26: Refactored into a function, as dictionaries can be passed in by other scripts calling it.
#Todo: Pass in other variables like delta, duration, size, etc. Delta may be deprecated entirely for another feature
def generate_ytt(ordered_sections, output_path="output.ytt"):

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

	# we need to know the start time of the current section so that the comment
	# timestamp can be adjusted. This variable keeps track of that.
	timeShift = 0 

	#Kai Change 10/28/26: Replaced keepIntervals loop with sections passed in from Byron's script, 
	#start and end variables defined by dictionary values instead.
	for section in ordered_sections:
		json_path = section["path"]
		startTime = section["start"]
		endTime = section["end"]

		# Open the specific JSON file needed for this section
		with open(json_path, 'r', encoding='UTF-8') as jsonFile:
			data = json.loads(jsonFile.read())

		# go through each comment and check whether it is inside the given interval or not
		for i in data['comments']:

			# get the original timestamp of the comment
			timeStamp = i['content_offset_seconds']

			# check whether the comment is between the given interval 
			if(timeStamp >= startTime and timeStamp <= endTime):

				# find how far the comment is from the startTime, then add where this section starts in the new combined output.
				# ex: assuming the given interval is (500, 550) and the comment is at 530 seconds, pos = 530 - 500 = 30, which means the comment appears 30 seconds after the start
				# of this interval. Since there could be other intervals processed before this one, their duration needs to be added to find the new timestamp
				pos = (timeStamp - startTime)
				timeStamp = timeShift + pos

				# original script
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

					#Kai Change 10/29/26: Indentation typo was breaking all messages past the first.
					colors.insert(userIndex, color)
				else:
					userIndex = users.index(display_name)

				#Kai Change 10/28/26: Escape character added to display name.
				texts.append('<s p="'+str(userIndex)+'">'+html.escape(display_name)+':</s><s p="1"> '+html.escape(message)+'</s>')

				#replace original timestamp with the updated timestamp
				timestamps.append([timeStamp + delta, True]) 
				timestamps.append([timeStamp + delta + duration, False])

		# add the duration of the current interval to timeShift
		timeShift += endTime - startTime

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

	"""
	if len(sys.argv) == 3:
		with open(sys.argv[2], 'w', encoding='UTF8') as outputFile:
			outputFile.write(header+middle+output+footer)
		else:
			print(header+middle+output+footer)
	"""


	with open("output.ytt", 'w', encoding='UTF-8') as outputFile:
		outputFile.write(header + middle + output + footer)

	print(header+middle+output+footer)