"""Integration test against the supplied patch; uses real Tk callbacks and parser."""
import ast, hashlib, time, unittest, os
from pathlib import Path
from types import SimpleNamespace
import original_readonly as ui
from readonly_ui import ReadOnlyWindow

ROOT=Path(__file__).parent
PATCH=Path(os.environ.get('HD2_TEST_PATCH','__missing_test_patch__'))
GAME_DATA=os.environ.get('HD2_TEST_GAME_DATA','')

class ReadOnlyTests(unittest.TestCase):
    def test_no_output_or_edit_functions(self):
        for file in ('readonly_ui.py','original_readonly.py','readonly_core.py'):
            tree=ast.parse((ROOT/file).read_text(encoding='utf-8'))
            bad=[]
            for n in ast.walk(tree):
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith(('save','write_patch','dump','export','import_wav','import_wem','import_audio','revert','apply_changes')):
                    bad.append(n.name)
            self.assertEqual(bad,[],file)
        self.assertNotIn('WwiseConsole',(ROOT/'readonly_env.py').read_text())

    @unittest.skipUnless(PATCH.is_file() and GAME_DATA,'Set HD2_TEST_PATCH and HD2_TEST_GAME_DATA for the 126-source/24-change fixture')
    def test_real_drop_comparison_and_readonly_menu(self):
        digest=hashlib.sha256(PATCH.read_bytes()).hexdigest()
        w=ui.MainWindow(ui.ArchiveSearch,ui.AudioPlayerWindow,check_updates=False)
        w.app_state.game_data_path=GAME_DATA
        try:
            w.root.withdraw()
            self.assertFalse(hasattr(w,'workspace'))
            self.assertFalse(w.root.bind('<Control-s>'))
            menu=[w.menu.entrycget(i,'label') for i in range(w.menu.index('end')+1)]
            self.assertEqual(menu,['文件','视图','选项','关于'])
            # Tk's file-drop representation, including a non-ASCII path.
            dropped=SimpleNamespace(data='{'+str(PATCH)+'}')
            self.assertEqual(w.drop_import(dropped),'copy')
            end=time.monotonic()+30
            while w.busy and time.monotonic()<end:
                w.root.update();time.sleep(.02)
            self.assertFalse(w.busy)
            a=w.mod_handler.archive
            self.assertIsNotNone(a)
            changed=[x for x in a.audio_sources.values() if x.modified]
            self.assertEqual(len(changed),24)
            self.assertEqual(len(w.treeview.tag_has('modified')),25)
            audio_items=[x for b in w.treeview.get_children() for k in w.treeview.get_children(b) for x in w.treeview.get_children(k) if w.treeview.item(x,'values')[0]=='音频源']
            self.assertEqual(len(audio_items),126)
            w.treeview.selection_set(audio_items[0]); w.show_info_window()
            def texts(widget):
                out=[]
                try:out.append(widget.cget('text'))
                except:pass
                for c in widget.winfo_children():out.extend(texts(c))
                return out
            self.assertFalse(any(s in ('Apply','应用','Add Make Up Gain','添加增益','保存') for s in texts(w.entry_info_panel)))
            w.create_hierarchy_view();w.root.update()
            self.assertTrue(w.treeview.get_children())
            # Repeat import must still compare against fresh vanilla data.
            w.drop_import(dropped)
            end=time.monotonic()+30
            while w.busy and time.monotonic()<end:
                w.root.update();time.sleep(.02)
            self.assertFalse(w.busy)
            self.assertEqual(sum(x.modified for x in w.mod_handler.archive.audio_sources.values()),24)
        finally:w.on_close()
        self.assertEqual(digest,hashlib.sha256(PATCH.read_bytes()).hexdigest())

if __name__=='__main__':unittest.main()
