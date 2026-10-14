"""Read-only controllers for the original upstream layout."""
import os, sys, json, queue, threading, sqlite3, re
from pathlib import Path
from types import SimpleNamespace
import tkinter
import tkinter.font as tkfont
from tkinter import *
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES
from readonly_core import *
from readonly_env import BASE, ASSETS
from readonly_log import logger
from update_service import APP_NAME, APP_VERSION, UpdateChecks
import webbrowser

class IconButton(ttk.Button):
    """Vector-derived images keep controls consistent across fonts and DPI levels."""
    symbols={'⏵':'play','▶':'play','⏸':'pause','↑':'up','↓':'down'}
    def __init__(self,master,icon_name=None,**kw):
        self.icon_name=icon_name or self.symbols.get(kw.get('text',''))
        self.icon_root=master.winfo_toplevel()
        if self.icon_name:
            kw['image']=self.icon_root.ui_icons[self.icon_root.icon_theme,self.icon_name]
            kw['text']=''
        super().__init__(master,**kw)
        self.icon_root.icon_buttons.append(self)
    def configure(self,cnf=None,**kw):
        if cnf is None and not kw:return super().configure()
        if isinstance(cnf,dict):kw={**cnf,**kw};cnf=None
        if kw.get('text') in self.symbols:
            self.icon_name=self.symbols[kw['text']];kw['text']=''
        if self.icon_name:kw['image']=self.icon_root.ui_icons[self.icon_root.icon_theme,self.icon_name]
        return super().configure(cnf,**kw)
    config=configure

class Names:
    def __init__(self):
        self.items={}
        path=ASSETS/'friendlynames.db'
        if path.exists():
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as con:
                for r in con.execute('SELECT id,name,friendlyname,archive,language FROM soundbanks'):
                    self.items[str(r[0])]=SimpleNamespace(id=str(r[0]),name=r[1],friendlyname=r[2],archive=r[3],language=r[4],success=True)
    def lookup_soundbank(self,key):
        return self.items.get(str(key),SimpleNamespace(success=False,archive='',friendlyname=str(key)))
    def query_soundbanks(self,language=''):
        return [v for v in self.items.values() if not language or v.language in (language,'none')]

class ReadOnlyModel:
    def __init__(self,archive=None):
        self.archive=archive
    def get_active_mod(self): return self
    def get_game_archives(self): return {self.archive.name:self.archive} if self.archive else {}
    def get_audio_source(self,key): return self.archive.audio_sources[key]
    def get_hierarchy_entry(self,key): return self.archive.hierarchy_entries[key]
    def get_string_entry(self,bid,key): return self.archive.text_banks[bid].entries[key]

def load_for_comparison(path,game_dir,lookup):
    """Import Patch File semantics: fresh original baseline, memory-only comparison."""
    archive=GameArchive.from_file(path)
    if archive is None or archive.magic != 0xF0000011:
        raise ValueError('无法读取该归档。')
    warnings=[]; base_cache={}; counts={'changed':0,'same':0,'unknown':0}
    import slim
    if game_dir and Path(game_dir).is_dir():
        slim.package_contents.clear(); slim.bundle_offsets.clear(); slim.done_init=False
        slim.slim_init(game_dir)
    for bid,bank in archive.wwise_banks.items():
        match=lookup.lookup_soundbank(bid)
        base=None
        if game_dir and match.success:
            if match.archive not in base_cache:
                try: base_cache[match.archive]=GameArchive.from_file(str(Path(game_dir)/match.archive))
                except Exception as exc:
                    base_cache[match.archive]=None
                    warnings.append(f'原版归档 {match.archive} 读取失败：{exc}')
            base=base_cache[match.archive]
        old_bank=base.wwise_banks.get(bid) if base else None
        for sid in bank.get_content():
            audio=archive.audio_sources.get(sid)
            if audio is None: continue
            old=base.audio_sources.get(sid) if old_bank and sid in old_bank.get_content() else None
            audio.comparison='未找到原版'
            if old is not None:
                audio.data_old=bytes(old.get_data())
                audio.modified=bytes(audio.get_data()) != audio.data_old
                audio.comparison='与原版不同' if audio.modified else '与原版相同'
                counts['changed' if audio.modified else 'same']+=1
            else: counts['unknown']+=1
        bank.modified=any(archive.audio_sources[s].modified for s in bank.get_content() if s in archive.audio_sources)
    for audio in archive.audio_sources.values():
        for parent in audio.parents:
            if hasattr(parent,'modified') and audio.modified: parent.modified=True
    return archive,counts,warnings

class ReadOnlyWindow:
    dark_mode_modified_bg='#ffffff'; dark_mode_modified_fg='#333333'
    def __init__(self,ArchiveSearch,AudioPlayerWindow,check_updates=True):
        # Establish DPI awareness before creating any Tk window to avoid bitmap stretching.
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass
        self.root=TkinterDnD.Tk()
        self.root.title(APP_NAME)
        self.root.geometry('1320x820'); self.root.minsize(820,560)
        families=set(tkfont.families(self.root))
        self.font_family=next((f for f in ('Microsoft YaHei UI','Microsoft YaHei','Segoe UI') if f in families),'TkDefaultFont')
        for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont','TkCaptionFont','TkSmallCaptionFont','TkIconFont','TkTooltipFont'):
            tkfont.nametofont(name).configure(family=self.font_family,size=10,weight='normal')
        self.root.option_add('*Font',(self.font_family,10))
        self.root.option_add('*TCombobox*Listbox.font',(self.font_family,10))
        self.menu_font=tkfont.Font(root=self.root,family=self.font_family,size=11,weight='normal')
        self.root.option_add('*Menu.font',self.menu_font)
        self.root.icon_buttons=[];self.root.icon_theme='dark'
        target=round(18*self.root.winfo_fpixels('1i')/96)
        size=min((16,20,24,28,32,40),key=lambda n:abs(n-target))
        self.root.ui_icons={(theme,name):PhotoImage(master=self.root,file=str(ASSETS/'ui_assets'/f'{theme}-{name}-{size}.png')) for theme in ('dark','light') for name in ('play','pause','up','down','check','blank')}
        self.app_icon=PhotoImage(master=self.root,file=str(ASSETS/'ui_assets'/'app.png'))
        self.root.iconphoto(True,self.app_icon)
        self.layout_job=None; self.layout_mode=None; self.header_mode=None
        self.root.report_callback_exception=lambda t,e,tb: messagebox.showerror('操作失败',str(e),parent=self.root)
        self.events=queue.Queue(); self.busy=False; self.search_results=[]; self.search_result_index=0
        self.updates=UpdateChecks(self.events,ASSETS/'friendlynames.db')
        self.update_dialogs={}
        self.app_state=SimpleNamespace(theme='dark_mode',ui_scale=1.0,rowheight_scale=1.0,game_data_path='')
        settings=ASSETS/'readonly_defaults.json'
        if settings.exists(): self.app_state.game_data_path=json.loads(settings.read_text(encoding='utf-8')).get('game_data_path','')
        self.name_lookup=Names(); self.mod_handler=ReadOnlyModel()
        self.ArchiveSearch=ArchiveSearch
        self.sound_handler=SoundHandler.get_instance()
        self.root.tk.call('source',str(ASSETS/'azure.tcl'))
        self.root.tk.call('set_theme','dark')
        self.top_bar=ttk.Frame(self.root,padding=(16,12,16,10)); self.top_bar.pack(side='top',fill='x')
        self.library_group=ttk.Frame(self.top_bar)
        ttk.Label(self.library_group,text='资源库',style='Muted.TLabel').grid(row=0,column=0,padx=(0,10))
        self.archive_search=ArchiveSearch('{1} || {0}',entries={v.id:v for v in self.name_lookup.query_soundbanks()},on_select_cb=self.on_archive_search_bar_return,master=self.library_group,width=24,font=(self.font_family,10))
        self.archive_search.grid(row=0,column=1,sticky='ew',padx=(0,8)); self.library_group.columnconfigure(1,weight=1)
        self.languages={'全部语言':'','英语':'English','西班牙语（西班牙）':'Spanish, Castilian','西班牙语（拉美）':'Spanish, Latin America','法语':'French','意大利语':'Italian','德语':'German','日语':'Japanese','葡萄牙语':'Portuguese','中文':'Chinese'}
        self.category_search=ttk.Combobox(self.library_group,state='readonly',width=12,values=list(self.languages))
        self.category_search.current(0); self.category_search.grid(row=0,column=2)
        self.category_search.bind('<<ComboboxSelected>>',self.on_category_search_bar_select)
        self.search_text_var=StringVar(self.root)
        self.search_group=ttk.Frame(self.top_bar)
        ttk.Label(self.search_group,text='查找',style='Muted.TLabel').grid(row=0,column=0,padx=(0,10))
        self.search_bar=ttk.Entry(self.search_group,textvariable=self.search_text_var,font=(self.font_family,10),width=18)
        self.search_label=ttk.Label(self.search_group,width=6,anchor='center',style='Muted.TLabel')
        self.search_bar.grid(row=0,column=1,sticky='ew'); self.search_group.columnconfigure(1,weight=1)
        IconButton(self.search_group,icon_name='up',width=3,command=self.search_up,style='Compact.TButton').grid(row=0,column=2,padx=(8,2))
        IconButton(self.search_group,icon_name='down',width=3,command=self.search_down,style='Compact.TButton').grid(row=0,column=3,padx=2)
        self.search_label.grid(row=0,column=4,padx=(4,0))
        self.player_group=ttk.Frame(self.top_bar)
        self.window=PanedWindow(self.root,orient=HORIZONTAL,borderwidth=0,sashwidth=6,sashrelief='flat',opaqueresize=True)
        self.status=StringVar(value='拖入补丁开始对照，高亮显示不同项。')
        self.status_label=ttk.Label(self.root,textvariable=self.status,anchor='w',padding=(16,9),style='Muted.TLabel')
        self.status_label.pack(side='bottom',fill='x')
        self.window.pack(fill=BOTH,expand=True)
        self.treeview_panel=Frame(self.window)
        self.scroll_bar=ttk.Scrollbar(self.treeview_panel,orient=VERTICAL)
        self.treeview=ttk.Treeview(self.treeview_panel,columns=('type',),height=20,selectmode='browse')
        self.scroll_bar.pack(side='right',pady=8,fill='y',padx=(0,8))
        self.treeview.pack(side='left',padx=(12,0),pady=8,fill='both',expand=True)
        self.treeview.heading('#0',text='文件'); self.treeview.heading('type',text='类型')
        self.treeview.column('#0',width=390,minwidth=160,stretch=True); self.treeview.column('type',width=110,minwidth=90,stretch=False)
        self.treeview.configure(yscrollcommand=self.scroll_bar.set); self.scroll_bar.configure(command=self.treeview.yview)
        self.treeview.tag_configure('modified',background='#ffffff',foreground='#333333')
        self.treeview.tag_configure('unknown',foreground='#ffcb6b')
        self.info_container=ttk.Frame(self.window)
        self.info_canvas=Canvas(self.info_container,highlightthickness=0,borderwidth=0,width=420)
        self.info_scroll=ttk.Scrollbar(self.info_container,orient='vertical',command=self.info_canvas.yview)
        self.info_canvas.configure(yscrollcommand=self.info_scroll.set)
        self.info_scroll.pack(side='right',fill='y',padx=(0,8),pady=8)
        self.info_canvas.pack(side='left',fill='both',expand=True)
        self.entry_info_panel=Frame(self.info_canvas,padx=16,pady=12)
        self.info_window=self.info_canvas.create_window(0,0,window=self.entry_info_panel,anchor='nw')
        self.entry_info_panel.bind('<Configure>',lambda e:self.info_canvas.configure(scrollregion=self.info_canvas.bbox('all')))
        self.info_canvas.bind('<Configure>',self.resize_info)
        self.info_canvas.bind('<MouseWheel>',self.scroll_info)
        self.window.add(self.treeview_panel,minsize=380,stretch='always'); self.window.add(self.info_container,minsize=280,stretch='always')
        self.audio_player=AudioPlayerWindow(self.player_group)
        self.audio_player.name_label.configure(anchor='w',style='Muted.TLabel')
        self.audio_player.name_label.pack_configure(fill='x',pady=(0,5))
        self.audio_player.frame.pack_configure(padx=0,pady=0)
        self.audio_player.play_button.configure(style='Compact.TButton',width=3)
        self.audio_player.start_label.configure(font=('Segoe UI',10))
        self.audio_player.end_label.configure(font=('Segoe UI',10))
        self.audio_player.slider.pack_configure(padx=10)
        self.audio_player.set_slider_callback(self.update_audio_slider)
        # Audio callbacks post to the UI queue, never touch Tk from a playback thread.
        self.sound_handler.update_func=lambda t:self.events.put(('time',t))
        self.sound_handler.start_func=lambda t:self.events.put(('duration',t))
        self.menu=Menu(self.root,tearoff=0,font=self.menu_font); self.file_menu=Menu(self.menu,tearoff=0,font=self.menu_font)
        self.file_menu.add_command(label='打开归档…',command=self.load_archive)
        self.file_menu.add_command(label='导入补丁内容',command=self.import_patch)
        self.file_menu.add_command(label='查看补丁内容',command=self.view_patch_content)
        self.file_menu.add_separator(); self.file_menu.add_command(label='退出',command=self.on_close)
        self.menu.add_cascade(label='文件',menu=self.file_menu)
        self.selected_view=StringVar(value='SourceView'); self.view_menu=Menu(self.menu,tearoff=0,font=self.menu_font)
        # Native Windows radio-menu marks can ignore Tk theme colors.
        # Render the selection with a theme-aware image instead of the OS glyph.
        self.view_menu.add_command(label='音频源',compound='left',command=lambda:self.select_view('SourceView'))
        self.view_menu.add_command(label='层级结构',compound='left',command=lambda:self.select_view('HierarchyView'))
        self.menu.add_cascade(label='视图',menu=self.view_menu)
        self.options_menu=Menu(self.menu,tearoff=0,font=self.menu_font)
        self.options_menu.add_command(label='选择游戏数据目录…',command=self.choose_game)
        self.options_menu.add_command(label='深色主题',command=lambda:self.theme('dark'))
        self.options_menu.add_command(label='浅色主题',command=lambda:self.theme('light'))
        self.menu.add_cascade(label='选项',menu=self.options_menu)
        self.about_menu=Menu(self.menu,tearoff=0,font=self.menu_font)
        self.about_menu.add_command(label='检查软件更新',command=lambda:self.show_update_dialog('software'))
        self.about_menu.add_command(label='检查数据库更新',command=lambda:self.show_update_dialog('database'))
        self.menu.add_cascade(label='关于',menu=self.about_menu)
        self.root.configure(menu=self.menu)
        self.treeview.bind('<<TreeviewSelect>>',self.show_info_window)
        self.treeview.bind('<Double-Button-1>',self.play_selection); self.treeview.bind('<Return>',self.play_selection)
        self.treeview.bind('<Button-3>',self.context_menu)
        self.search_bar.bind('<Return>',self.search_bar_on_enter_key)
        for widget in (self.root,self.treeview,self.entry_info_panel):
            widget.drop_target_register(DND_FILES); widget.dnd_bind('<<Drop>>',self.drop_import)
        self.root.bind('<Control-o>',lambda e:self.load_archive()); self.root.bind('<Control-i>',lambda e:self.import_patch())
        self.root.bind('<Control-f>',lambda e:self.search_bar.focus_set())
        self.root.protocol('WM_DELETE_WINDOW',self.on_close)
        self.theme('dark'); self.root.after(80,self.poll)
        self.root.bind('<Configure>',self.schedule_layout,add='+')
        self.root.after_idle(self.reflow)
        self.show_empty_state()
        if check_updates:self.root.after(300,self.start_update_checks)

    def start_update_checks(self):
        for kind in ('software','database'):self.updates.start(kind)

    def show_update_dialog(self,kind):
        existing=self.update_dialogs.get(kind)
        if existing and existing.window.winfo_exists():
            existing.window.lift();return
        title='检查软件更新' if kind=='software' else '检查数据库更新'
        window=Toplevel(self.root);window.title(title);window.transient(self.root)
        window.configure(background=self.palette['bg']);window.minsize(540,300)
        body=ttk.Frame(window,padding=24);body.pack(fill='both',expand=True)
        body.columnconfigure(0,weight=1)
        row=0
        def line(text,url=None):
            nonlocal row
            label=ttk.Label(body,text=text,wraplength=620,justify='left')
            label.grid(row=row,column=0,sticky='ew',pady=(0,10));row+=1
            if url:
                label.configure(cursor='hand2')
                label.bind('<Button-1>',lambda e:webbrowser.open(url))
            return label
        if kind=='software':
            line(f'{APP_NAME}   {APP_VERSION}')
            url='https://github.com/'+self.updates.repos[kind]
            line('软件 GitHub：'+url,url)
            line('原作者：RaidingForPants (Evelyn)')
            line('原作者 GitHub：https://github.com/RaidingForPants','https://github.com/RaidingForPants')
            line('原项目：https://github.com/RaidingForPants/hd2-audio-modder','https://github.com/RaidingForPants/hd2-audio-modder')
            line('感谢原作者及贡献者提供 HD2 Audio Modder 和音频数据库。本软件基于原项目制作，保留音频浏览、对照和试听功能。')
        else:
            line('当前数据库版本：'+self.updates.current[kind])
            url='https://github.com/'+self.updates.repos[kind]
            line('数据库 GitHub：'+url,url)
            line('数据库提供资源名称和归档映射。检查更新不会自动替换本地数据库。')
        state=StringVar(master=window)
        ttk.Label(body,textvariable=state,wraplength=620,justify='left').grid(row=row,column=0,sticky='ew',pady=(8,14));row+=1
        actions=ttk.Frame(body);actions.grid(row=row,column=0,sticky='e')
        retry=ttk.Button(actions,text='重新检查',command=lambda:self.retry_update(kind))
        retry.pack(side='left',padx=4)
        update=ttk.Button(actions,text='更新软件（打开发布页）' if kind=='software' else '查看数据库新版',command=lambda:webbrowser.open(self.updates.results[kind]['url']))
        ttk.Button(actions,text='关闭',command=window.destroy).pack(side='right',padx=4)
        self.update_dialogs[kind]=SimpleNamespace(window=window,state=state,retry=retry,update=update)
        if kind not in self.updates.results:self.updates.start(kind)
        self.refresh_update_dialog(kind)

    def retry_update(self,kind):
        self.updates.start(kind);self.refresh_update_dialog(kind)

    def refresh_update_dialog(self,kind):
        dialog=self.update_dialogs.get(kind)
        if not dialog or not dialog.window.winfo_exists():return
        result=self.updates.results[kind]
        dialog.state.set(result['message'])
        dialog.retry.configure(state='disabled' if kind in self.updates.running else 'normal')
        dialog.update.pack_forget()
        if result.get('newer'):dialog.update.pack(side='left',padx=4)

    def theme(self,value):
        self.root.tk.call('set_theme',value)
        self.app_state.theme=value+'_mode'
        self.root.icon_theme=value
        for button in self.root.icon_buttons:
            if button.winfo_exists() and button.icon_name:button.configure(image=self.root.ui_icons[value,button.icon_name])
        dark=value=='dark'
        self.palette={'bg':'#25282e' if dark else '#f5f6f8','panel':'#202329' if dark else '#ffffff','text':'#e5e8ed' if dark else '#242a32','muted':'#a1aab8' if dark else '#606b7b','selected':'#354b6a' if dark else '#d8e6f8'}
        style=ttk.Style(self.root); p=self.palette
        style.configure('.',font=(self.font_family,10))
        style.configure('TFrame',background=p['bg'])
        style.configure('TLabel',background=p['bg'],foreground=p['text'])
        style.configure('Muted.TLabel',foreground=p['muted'])
        style.configure('Title.TLabel',font=(self.font_family,12,'bold'))
        style.configure('TButton',font=(self.font_family,10),padding=(12,7))
        style.configure('Compact.TButton',padding=(5,5))
        style.configure('TEntry',padding=7)
        style.configure('TCombobox',padding=6)
        line=tkfont.nametofont('TkDefaultFont').metrics('linespace')
        style.configure('Treeview',font=(self.font_family,10),rowheight=line+12,background=p['panel'],fieldbackground=p['panel'],foreground=p['text'],borderwidth=0)
        style.configure('Treeview.Heading',font=(self.font_family,10,'bold'),padding=(10,9))
        style.map('Treeview',background=[('selected',p['selected'])],foreground=[('selected',p['text'])])
        self.treeview.tag_configure('modified',background='#334333' if dark else '#e6f2e6',foreground='#c6e7bb' if dark else '#235323')
        self.treeview.tag_configure('unknown',foreground='#ebc47c' if dark else '#916014')
        self.root.configure(background=p['bg']); self.window.configure(background=p['bg'])
        self.info_canvas.configure(background=p['bg'])
        self.paint_frames(self.root)
        for menu in (self.menu,self.file_menu,self.view_menu,self.options_menu,self.about_menu):
            self.style_menu(menu)
        self.update_view_marks()

    def style_menu(self,menu):
        p=self.palette
        menu.configure(background=p['bg'],foreground=p['text'],activebackground=p['selected'],activeforeground=p['text'],selectcolor=p['text'])

    def update_view_marks(self):
        for index,mode in enumerate(('SourceView','HierarchyView')):
            name='check' if self.selected_view.get()==mode else 'blank'
            self.view_menu.entryconfigure(index,image=self.root.ui_icons[self.root.icon_theme,name])

    def select_view(self,mode):
        self.selected_view.set(mode)
        self.update_view_marks()
        self.create_source_view() if mode=='SourceView' else self.create_hierarchy_view()

    def paint_frames(self,widget):
        if isinstance(widget,Frame):widget.configure(background=self.palette['bg'])
        for child in widget.winfo_children():self.paint_frames(child)

    def schedule_layout(self,event=None):
        if event is not None and event.widget is not self.root:return
        if self.layout_job is not None:self.root.after_cancel(self.layout_job)
        self.layout_job=self.root.after(50,self.reflow)

    def reflow(self):
        self.layout_job=None
        width=self.root.winfo_width()
        mode='wide' if width>=1100 else 'narrow'
        if mode!=self.header_mode:
            self.header_mode=mode
            for frame in (self.library_group,self.search_group,self.player_group):frame.grid_forget()
            self.top_bar.columnconfigure(0,weight=3)
            self.top_bar.columnconfigure(1,weight=2 if mode=='wide' else 0)
            if mode=='wide':
                self.library_group.grid(row=0,column=0,sticky='ew',padx=(0,24))
                self.search_group.grid(row=0,column=1,sticky='ew')
                self.player_group.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(12,0))
            else:
                self.library_group.grid(row=0,column=0,sticky='ew')
                self.search_group.grid(row=1,column=0,sticky='ew',pady=(8,0))
                self.player_group.grid(row=2,column=0,sticky='ew',pady=(10,0))
        vertical=width<960
        orient='vertical' if vertical else 'horizontal'
        if orient!=self.layout_mode:
            self.layout_mode=orient; self.window.configure(orient=orient)
            self.window.paneconfigure(self.treeview_panel,minsize=180 if vertical else 380)
            self.window.paneconfigure(self.info_container,minsize=140 if vertical else 280)
            self.root.after_idle(self.position_sash)
        self.status_label.configure(wraplength=max(400,width-48))
        self.wrap_info()

    def position_sash(self):
        if self.layout_mode=='vertical':self.window.sash_place(0,0,max(180,int(self.window.winfo_height()*.6)))
        else:self.window.sash_place(0,int(self.window.winfo_width()*.57),0)
        self.wrap_info()

    def wrap_info(self):
        width=max(220,self.entry_info_panel.winfo_width()-52)
        for child in self.entry_info_panel.winfo_children():
            child.bind('<MouseWheel>',self.scroll_info)
            if isinstance(child,ttk.Label):child.configure(wraplength=width)

    def resize_info(self,event):
        self.info_canvas.itemconfigure(self.info_window,width=event.width)
        self.root.after_idle(self.wrap_info)

    def scroll_info(self,event):
        if self.entry_info_panel.winfo_reqheight()>self.info_canvas.winfo_height():
            self.info_canvas.yview_scroll(-1 if event.delta>0 else 1,'units')
        return 'break'

    def show_empty_state(self):
        ttk.Label(self.entry_info_panel,text='音频信息',style='Title.TLabel').pack(anchor='w',pady=(2,12))
        ttk.Label(self.entry_info_panel,text='选择左侧的音频，查看信息并试听。',style='Muted.TLabel',wraplength=350).pack(anchor='w')

    def choose_game(self):
        if self.busy: return
        path=filedialog.askdirectory(title='选择绝地潜兵 2 的 data 目录',parent=self.root)
        if path:
            self.app_state.game_data_path=path
            self.status.set('当前游戏目录：'+path+'；重新导入补丁即可对照。')
        return path

    def run_task(self,fn):
        if self.busy:
            self.status.set('正在读取，请等待当前任务完成。'); return
        self.busy=True; self.sound_handler.pause()
        self.status.set('正在读取原版并对照补丁，请稍候……')
        def work():
            try:self.events.put(('loaded',fn()))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='update_result':
                    target,result=value
                    self.updates.complete(target,result);self.refresh_update_dialog(target)
                    self.about_menu.entryconfigure(0 if target=='software' else 1,label=('检查软件更新' if target=='software' else '检查数据库更新')+(' · 有更新' if result.get('newer') else ''))
                    continue
                if kind=='time': self.audio_player.set_time(value); continue
                if kind=='duration':self.audio_player.set_new_audio(value); continue
                if kind=='ended':self.audio_player.audio_finished(); continue
                if kind=='playerror':self.status.set('试听失败：'+value); continue
                self.busy=False
                if kind=='error':
                    self.status.set('读取失败：'+value); messagebox.showerror('读取失败',value,parent=self.root); continue
                archive,counts,warnings=value
                self.sound_handler.kill_sound(); self.audio_player.reset()
                self.mod_handler=ReadOnlyModel(archive)
                self.create_source_view() if self.selected_view.get()=='SourceView' else self.create_hierarchy_view()
                for child in self.entry_info_panel.winfo_children():child.destroy()
                for top in self.treeview.get_children():
                    for bank in self.treeview.get_children(top):self.treeview.item(bank,open=True)
                self.show_empty_state()
                self.status.set(f"对照完成 · {counts['changed']} 条不同（已高亮） · {counts['same']} 条相同 · {counts['unknown']} 条未对照" if counts else '已打开原始内容，尚未对照。')
                if warnings:self.status.set(self.status.get()+' '+warnings[0])
        except queue.Empty:pass
        self.root.after(80,self.poll)

    def import_patch(self,archive_file=''):
        if self.busy:return
        path=archive_file or filedialog.askopenfilename(title='导入补丁文件并对照',filetypes=[('补丁文件','*.patch_*'),('所有文件','*')],parent=self.root)
        if not path:return
        if not Path(self.app_state.game_data_path).is_dir() or not self.app_state.game_data_path:
            if not self.choose_game():
                self.status.set('未选择游戏 data 目录，未执行对照。'); return
        self.run_task(lambda:load_for_comparison(path,self.app_state.game_data_path,self.name_lookup))

    def load_archive(self,initialdir='',archive_file=''):
        path=archive_file or filedialog.askopenfilename(title='打开归档',initialdir=initialdir or self.app_state.game_data_path,parent=self.root)
        if not path:return
        if re.search(r'\.patch_\d+$',path,re.I):return self.import_patch(path)
        self.run_task(lambda:(self.read_plain(path),None,[]))

    def read_plain(self,path):
        import slim
        if not Path(path).exists() and self.app_state.game_data_path:slim.slim_init(self.app_state.game_data_path)
        archive=GameArchive.from_file(path)
        if archive is None:raise ValueError('未能读取归档。')
        return archive

    def view_patch_content(self):
        path=filedialog.askopenfilename(title='查看补丁内容',filetypes=[('补丁文件','*.patch_*')],parent=self.root)
        if path:self.run_task(lambda:(self.read_plain(path),None,[]))

    def drop_import(self,event):
        paths=self.root.tk.splitlist(event.data)
        if len(paths)!=1:
            messagebox.showinfo('提示','每次请拖入一个补丁，避免不同模组混作对照基准。',parent=self.root);return
        if re.search(r'\.patch_\d+$',paths[0],re.I):self.import_patch(paths[0])
        else:self.load_archive(archive_file=paths[0])
        return 'copy'

    def mark_modified(self,entry,item=None):
        if item and entry.modified:self.treeview.item(item,tags=tuple(self.treeview.item(item,'tags'))+('modified',))
        elif item and isinstance(entry,AudioSource) and getattr(entry,'comparison','')=='未找到原版':
            self.treeview.item(item,tags=tuple(self.treeview.item(item,'tags'))+('unknown',))

    def show_info_window(self,event=None):
        items=self.treeview.selection()
        if len(items)!=1:return
        for child in self.entry_info_panel.winfo_children():child.destroy()
        self.info_canvas.yview_moveto(0)
        item=items[0]; kind=self.treeview.item(item,'values')[0]; tags=self.treeview.item(item,'tags')
        title=self.treeview.item(item,'text')
        ttk.Label(self.entry_info_panel,text=title,style='Title.TLabel',wraplength=420,justify='left').pack(anchor='w',pady=(2,14))
        if kind=='音频源':
            audio=self.mod_handler.get_active_mod().get_audio_source(int(tags[0]))
            buttons=ttk.Frame(self.entry_info_panel);buttons.pack(anchor='w',pady=(0,16))
            ttk.Button(buttons,text='试听音频',command=lambda:self.play_audio(audio.get_id())).pack(side='left',padx=(0,8))
            if audio.data_old:
                ttk.Button(buttons,text='试听原版',command=lambda:self.play_audio(-audio.get_id())).pack(side='left')
            ttk.Label(self.entry_info_panel,text='对照状态',style='Muted.TLabel').pack(anchor='w',pady=(0,4))
            ttk.Label(self.entry_info_panel,text=getattr(audio,'comparison','尚未对照')).pack(anchor='w',pady=(0,16))
            ttk.Label(self.entry_info_panel,text='父级 Wwise 播放对象 ID',style='Muted.TLabel').pack(anchor='w',pady=(0,4))
            ttk.Label(self.entry_info_panel,text=' · '.join(str(p.get_id()) for p in audio.parents),wraplength=420,justify='left').pack(anchor='w')
        elif kind=='归档文件':ttk.Label(self.entry_info_panel,text='只读归档浏览').pack(anchor='w',padx=8)
        else:
            ttk.Label(self.entry_info_panel,text=f'{kind} ID：{tags[0]}',wraplength=650).pack(anchor='w',padx=8)
            if kind=='文本':
                entry=self.mod_handler.get_string_entry(int(tags[1]),int(tags[0]))
                ttk.Label(self.entry_info_panel,text=entry.get_text(),wraplength=650).pack(anchor='w',padx=8,pady=8)
        self.wrap_info()

    def context_menu(self,event):
        item=self.treeview.identify_row(event.y)
        if not item:return
        self.treeview.selection_set(item);self.show_info_window()
        menu=Menu(self.treeview,tearoff=0,font=self.menu_font);self.style_menu(menu);menu.add_command(label='复制 ID',command=self.copy_id)
        if self.treeview.item(item,'values')[0]=='音频源':menu.add_command(label='试听',command=self.play_selection)
        menu.tk_popup(event.x_root,event.y_root)

    def play_selection(self,event=None):
        items=self.treeview.selection()
        if len(items)==1 and self.treeview.item(items[0],'values')[0]=='音频源':self.play_audio(int(self.treeview.item(items[0],'tags')[0]))

    def play_audio(self,file_id):
        if self.busy:return
        audio=self.mod_handler.get_audio_source(abs(file_id))
        data=audio.data_old if file_id<0 else audio.get_data()
        if not data:return
        Path(TMP).mkdir(exist_ok=True)
        self.sound_handler.kill_sound()
        try:
            self.sound_handler.play_audio(file_id,data,callback=lambda:self.events.put(('ended',None)))
            self.audio_player.name_label.configure(text=f'正在播放：{abs(file_id)}.wem'+('（原版）' if file_id<0 else ''))
        except Exception as exc:self.status.set('试听失败：'+str(exc))

    def update_audio_slider(self,time):
        self.sound_handler.seek(float(time));self.audio_player.set_time(time,autoplay=False)

    def on_category_search_bar_select(self,event=None):
        language=self.languages[self.category_search.get()]
        self.archive_search.language=language
        self.archive_search.set_entries({v.id:v for v in self.name_lookup.query_soundbanks(language)})

    def on_archive_search_bar_return(self,value):
        if not self.app_state.game_data_path and not self.choose_game():return
        self.load_archive(archive_file=str(Path(self.app_state.game_data_path)/value.split(' || ')[-1]))

    def on_close(self):
        self.sound_handler.kill_sound()
        for job in self.root.tk.splitlist(self.root.tk.call('after','info')):
            self.root.after_cancel(job)
        self.root.destroy()
