import tkinter as tk
from tkinter import colorchooser

def pick_color():
    """打开颜色选择器并返回颜色值"""
    color = colorchooser.askcolor(title="选择颜色", initialcolor="#7BC85C")
    if color[1]:  # 用户选择了颜色
        print(f"选择的RGB值: {color[0]}")
        print(f"选择的十六进制值: {color[1]}")
        result_label.config(text=f"选中颜色: {color[1]}", bg=color[1])
        hex_entry.delete(0, tk.END)
        hex_entry.insert(0, color[1])
        return color[1]
    return None

# 创建主窗口
root = tk.Tk()
root.title("颜色选择器")
root.geometry("300x200")
root.configure(bg="#f5f5f5")

# 标题
title = tk.Label(root, text="颜色选择器", font=("微软雅黑", 16, "bold"), bg="#f5f5f5", fg="#333")
title.pack(pady=10)

# 当前颜色显示
result_label = tk.Label(root, text="当前颜色: #7BC85C", font=("微软雅黑", 12), 
                        bg="#7BC85C", fg="white", width=20, height=2)
result_label.pack(pady=10)

# 十六进制输入框
hex_frame = tk.Frame(root, bg="#f5f5f5")
hex_frame.pack(pady=5)
tk.Label(hex_frame, text="HEX:", font=("微软雅黑", 10), bg="#f5f5f5").pack(side=tk.LEFT)
hex_entry = tk.Entry(hex_frame, font=("微软雅黑", 10), width=10)
hex_entry.pack(side=tk.LEFT, padx=5)
hex_entry.insert(0, "#7BC85C")

# 选择颜色按钮
pick_btn = tk.Button(root, text="选择颜色", font=("微软雅黑", 12), 
                     bg="#2196F3", fg="white", relief=tk.FLAT,
                     cursor="hand2", command=pick_color)
pick_btn.pack(pady=10)

# 复制按钮
def copy_hex():
    root.clipboard_clear()
    root.clipboard_append(hex_entry.get())
    copy_btn.config(text="已复制!")
    root.after(1000, lambda: copy_btn.config(text="复制HEX"))

copy_btn = tk.Button(root, text="复制HEX", font=("微软雅黑", 10),
                     bg="#4CAF50", fg="white", relief=tk.FLAT,
                     cursor="hand2", command=copy_hex)
copy_btn.pack(pady=5)

# 运行
root.mainloop()
