import io
import json
import queue
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from update_service import check_release, UpdateChecks

class UpdateTests(unittest.TestCase):
    def test_versions_and_errors(self):
        def response(tag):
            def open_(request,timeout):
                self.assertEqual(timeout,6)
                return io.BytesIO(json.dumps({'tag_name':tag}).encode())
            return open_
        self.assertTrue(check_release('a/b','0.1.0',response('v0.2.0'))['newer'])
        self.assertFalse(check_release('a/b','17',response('v17.0'))['newer'])
        self.assertFalse(check_release('a/b','1.0',response('v1.0rc1'))['newer'])
        self.assertIn('无法识别',check_release('a/b','1.0',response('bad'))['message'])
        for code in (403,404,429,500):
            def fail(*args,**kwargs):raise HTTPError('url',code,'error',{},None)
            result=check_release('a/b','1',fail)
            self.assertFalse(result['newer'])
            self.assertNotIn('已是最新',result['message'])

    def test_parallel_checks_do_not_block_or_duplicate(self):
        gate=threading.Event(); calls=[]; events=queue.Queue()
        def checker(repo,current):
            calls.append(repo);gate.wait(3)
            return {'newer':False,'message':'done'}
        checks=UpdateChecks(events,Path(__file__).parent/'friendlynames.db',checker)
        begin=time.monotonic()
        checks.start('software');checks.start('software');checks.start('database')
        self.assertLess(time.monotonic()-begin,.5)
        gate.set()
        for _ in range(2):
            kind,(target,result)=events.get(timeout=3)
            checks.complete(target,result)
        self.assertEqual(len(calls),2)
        self.assertFalse(checks.running)

    def test_ui_results_and_close_during_check(self):
        # Each Tk interpreter owns native resources; isolate from parser UI tests.
        import subprocess, sys
        subprocess.run([sys.executable,'-c',
            'from test_updates import UpdateTests; UpdateTests().exercise_ui()'],
            cwd=Path(__file__).parent,check=True,timeout=15)

    def exercise_ui(self):
        import original_readonly as ui
        w=ui.MainWindow(ui.ArchiveSearch,ui.AudioPlayerWindow,check_updates=False)
        gate=threading.Event()
        try:
            w.root.withdraw()
            self.assertEqual(w.root.title(),'HD2AudioViewer')
            def checker(repo,current):
                gate.wait(3)
                return {'newer':True,'message':'发现新版本：0.2.0','url':'https://github.com/EyeMelody/HD2AudioViewer/releases'}
            w.updates.checker=checker
            w.start_update_checks()
            w.show_update_dialog('software');w.show_update_dialog('database')
            w.root.update()
            self.assertFalse(w.update_dialogs['software'].update.winfo_manager())
            self.assertEqual(str(w.update_dialogs['software'].retry.cget('state')),'disabled')
            w.busy=True
            gate.set()
            deadline=time.monotonic()+3
            while w.updates.running and time.monotonic()<deadline:
                w.root.update();time.sleep(.02)
            self.assertFalse(w.updates.running)
            self.assertTrue(w.busy)  # Update completion must not unlock archive loading.
            self.assertEqual(w.update_dialogs['software'].update.winfo_manager(),'pack')
            w.theme('light');w.theme('dark')
            w.retry_update('software')
        finally:
            gate.set();w.on_close()
        import gc
        del w
        gc.collect()

if __name__=='__main__':unittest.main()
