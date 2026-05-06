import os
import subprocess
import time
import argparse
import openrouter
import random
import requests
import atexit
import json
import sys
import ast

def read(file):
	with open (file, "r") as f:
		return f.read().strip()

# ========================== Configurations =========================================
API_KEY = read("Config/API_KEY")
URL = "https://openrouter.ai/api/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
prompt = read("prompt")
version = 0.2
chats_folder = "chat_history"
intro = f"""

		███████╗███████╗██╗   ██╗███████╗
		╚══███╔╝██╔════╝██║   ██║██╔════╝
		  ███╔╝ █████╗  ██║   ██║███████╗  
		 ███╔╝  ██╔══╝  ██║   ██║     ██║  
		███████╗███████╗╚██████╔╝███████║ v{version}
		╚══════╝╚══════╝ ╚═════╝ ╚══════╝

"""
chat_name = ""
add_msg = "add_msg"
new_msg = read(add_msg)

# ========================== COLOR PRINT =========================================
class C:
    RESET = "\033[0m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


def color_print(*args, color=None, **kwargs):
    """
    Drop-in replacement for print() with optional color support.
    
    Works with:
    - multiple arguments: print("a", "b")
    - end= / sep= / flush=
    """

    text = " ".join(str(a) for a in args)

    if color:
        text = f"{color}{text}{C.RESET}"

    print(text, **kwargs)
# =================================================================================

parser = argparse.ArgumentParser(description=f"Zeus{version} is an AI tool which interacts with online models and interact directly with your terminal to run commands and tools.")
parser.add_argument("-c", type=int, help="Choose a chat number, omit if you don't know the chats IDs")
parser.add_argument("-n", help="Create new chat and specify title")
args = parser.parse_args()

def append(target_file, new_content):
	with open(target_file, "a") as t:
		t.write(new_content)

def write(target_file, new_content):
	with open(target_file, "w") as t:
		t.write(new_content)
		
def empty(target_file):
	with open (target_file, "w") as t:
		pass

def json_append(target_file, new_content):
	try:
		with open(target_file, "r") as f:
			data = json.load(f)
	except (FileNotFoundError, json.JSONDecodeError):
		data = []

	data.append(new_content)

	with open(target_file, "w") as f:
		json.dump(data, f, indent=2)

def json_read(target_file):
	with open (target_file, "r") as t:
		content = t.read().strip()
	if content != "":
		with open(target_file, "r") as t:
			return json.load(t)
	else:
		return []

def overwrite(target_file):
	with open (target_file, "w") as t:
		t.write("")
		
def save_notes(chat_name, notes):
	notes_dir = "Notes"
	file_path = os.path.join(notes_dir, chat_name)
	write(file_path, notes)
	return

def run_cmd(cmd):
    if cmd.startswith("rm "):
        return {"stdout": "",
                "stderr": "Access Denied!",
                "returncode": -1
        }
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15
        )

        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }

    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Command timed out",
            "returncode": -1
        }
	
def new_chat(chat_history_file):
	history = read(chat_history_file)
	if history.strip() != "":
		return False
	else:
		return True

def choose_chat():
	chats = os.listdir(chats_folder)
	
	for i, chat in enumerate(chats, start=1):
		if not args.c:
			color_print(f"{i}. {chat}", color=C.CYAN)

	if not args.c:
		choice = int(input("\nChoose chat number: "))
	else:
		choice = int(args.c)
	if 1 <= choice <= len(chats):
		selected = chats[choice - 1]
		color_print(f"								{selected}", color=C.BLUE)
		return selected
		
	else:
		color_print("Invalid choice", color=C.RED)
		sys.exit()

def send_msg(user_input, prompt, notes=None, chat_history_file=None):
	message = [prompt]
	if not notes is None:
		history = json_read(chat_history_file)

		clean_history = []
		for m in history:
			content = m["content"]

			if not isinstance(content, str):
				content = json.dumps(content)

			clean_history.append({
				"role": m["role"],
				"content": content
			})

		message.extend(clean_history)

	if not chat_history_file is None:
		message.extend(json_read(chat_history_file))

	message.append({"role": "user", "content": json.dumps(user_input)})

	try:
		response = requests.post(URL, headers=headers, json={
			"model": "deepseek/deepseek-v4-flash",		#"openai/gpt-4o-mini",
			"messages": message
		})
	except requests.exceptions.ConnectionError:
		color_print("[!] You are not connected to the internet! Quitting...", color=C.RED)
		sys.exit()

	data = response.json()

	if "choices" not in data:
		return json.dumps({"error": data})

	reply = data["choices"][0]["message"]["content"]
	print(data)
	sys.exit()
	return reply

def start_processing(task, prompt, chat_history_file):
	notes_file = f"Notes/{chat_name}"
	if new_chat(chat_history_file):
		formatted_task = {"role": "user", "content": task}
		json_append(chat_history_file, formatted_task)
		response = send_msg(task, prompt)
		try:
			reply = json.loads(response)
		except json.JSONDecodeError:
			color_print("Invalid model output:", response, color=C.RED)
			return
		steps = reply["steps"]
		k = 0
		current_step = steps[k]
		notes = []
	else:
		try:
			notes_content = read(notes_file)
			try:
				notes = json_read(notes_file)
			except:
				notes = []

			response = send_msg(task, prompt, notes=notes, chat_history_file=chat_history_file)
		except FileNotFoundError:
			notes = []
			response = send_msg(task, prompt, chat_history_file=chat_history_file)
			
		try:
			reply = json.loads(response)
		except json.JSONDecodeError:
			color_print("Invalid model output:", response, color=C.RED)
			return
		last_msg = json_read(chat_history_file)[-1]["content"]

		if isinstance(last_msg, str):
			last_msg = json.loads(last_msg)

		current_step = last_msg["current_step"]
		steps = last_msg["steps"]

		try:
			k = steps.index(current_step)
		except ValueError:
			color_print("[!] current_step not found in steps list", color=C.RED)
			return

	msg = ""
	while True:
		formatted_reply = {
			"role": "assistant",
			"content": json.dumps(reply)
		}

		json_append(chat_history_file, formatted_reply)
		if reply["program_call"] == "End":
			color_print(reply["message"], color=C.GREEN)
			return
		elif reply["program_call"] == "Waiting":
			color_print(f"(?) {reply['message']}:\n\n>>> ", end="", color=C.YELLOW)
			msg = input()
		elif reply["program_call"] == "Done":
			steps[k] = "[success] " + steps[k]
			k += 1
			current_step = steps[k]
		elif reply["program_call"] == "Failed":
			steps[k] = "[Failed] " + steps[k]
			k += 1
			current_step = steps[k]
		if reply["notes"]:
			try:
				existing_notes = json_read(notes_file)
			except:
				existing_notes = []

			existing_notes.extend(reply["notes"])

			with open(notes_file, "w") as f:
				json.dump(existing_notes, f, indent=2)

		if reply["cmd"]:
			color_print(f"\n$ {reply['cmd']}\t\t\t", end="", color=C.CYAN)
			color_print(f"# {reply['message']}", color=C.GREEN)
			cmd_output = run_cmd(reply["cmd"])
			color_print(f"{cmd_output['stdout']}")
		else:
			cmd_output = ""
		if not msg:
			msg = read(add_msg)
			empty(add_msg)
			if not msg:
				msg = ""

		message = json.dumps({
	  "user_message": msg,
	  "command_output": cmd_output,
	  "steps": steps,
	  "current_step": current_step
	  })
		formatted_message = {"role": "user", "content": message}
		json_append(chat_history_file, formatted_message)
		response = send_msg(message, prompt, notes=notes, chat_history_file=chat_history_file)
		try:
			reply = json.loads(response)
		except json.JSONDecodeError:
			color_print("Invalid model output:", response, color=C.RED)
			return

def main():
	global prompt
	global chat_name
	color_print(intro, color=C.CYAN)
	if not args.n:
		chat_name = choose_chat()
		chat_history_file = os.path.join(chats_folder, chat_name)
		if not read(chat_history_file):
			color_print("[!] The chat is empty!", color=C.YELLOW)
		else:
#			color_print(read(chat_history_file), color=C.BLUE)
			for msg in json_read(chat_history_file):
				color_print(f"{msg['role']}: {msg['content']}\n", color=C.BLUE)

	else:
		chat_name = args.n
		chat_history_file = os.path.join(chats_folder, chat_name)
		if not os.path.exists(chat_history_file):
			with open (chat_history_file, "w") as nc:
				pass
		else:
			color_print(f"[!] The chat \"{chat_name}\" already exists!\n", color=C.YELLOW)
			if read(chat_history_file).strip() != "":
				for msg in json_read(chat_history_file):
					if msg['role'] == "user":
						message = msg['content']
					elif msg['role'] == "assistant":
						content = json.loads(msg['content'])
						message = content["message"]
					color_print(f"{msg['role']}: {message}\n", color=C.BLUE)

	color_print(">>> ", end="", color=C.CYAN)
	task = input("").strip()

	prompt = prompt + "\n" + task + "\"\"\"}"
	prompt = ast.literal_eval(prompt)         # Convert to dict
	
	start_processing(task, prompt, chat_history_file)

main()
