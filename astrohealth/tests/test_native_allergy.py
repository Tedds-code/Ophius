from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
import plistlib
from unittest.mock import patch

from app import AlertTracker
from astrohealth.allergies import AllergyGuard
from astrohealth.monitor import Monitor
from astrohealth.simulation import Simulator
from setup_desktop import install_macos

ROOT=Path(__file__).resolve().parents[1]


class NativeAllergyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.now=datetime(2026,11,15,12,tzinfo=timezone.utc)
        self.monitor=Monitor(Path(self.temp.name),ROOT/'config',ROOT/'profiles',clock=lambda:self.now)

    def tearDown(self):
        self.monitor.close();self.temp.cleanup()

    def report(self,**extra):
        return {'timestamp':self.now.isoformat(),'measurements':{'hemoglobin':{'value':11,'unit':'g/dL'}},**extra}

    def test_exact_family_and_combination_allergens_are_blocked(self):
        for name in ['penicillin','amoxicillin','ampicillin','amoxicillin/clavulanic acid']:
            check=self.monitor.check_medication('A-101',{'medication':name})
            self.assertTrue(check['blocked'],name)
            with self.assertRaisesRegex(ValueError,'blocked'):
                self.monitor.record_medication('A-101',{'medication':name,'recording_allowed':True})
        self.assertFalse(any(e['kind']=='medication_record' for e in self.monitor.history('A-101')['events']))

    def test_unknown_and_uncertain_drugs_need_review(self):
        for name in ['some brand product','antibiotic','ceftriaxone']:
            result=self.monitor.check_medication('A-101',{'medication':name})
            self.assertEqual(result['status'],'needs_review')
            self.assertFalse(result['recording_allowed'])
        self.monitor.update_allergies('A-102',{'allergies':['unknown']})
        self.assertFalse(self.monitor.check_medication('A-102',{'medication':'acetaminophen'})['recording_allowed'])
        self.monitor.update_allergies('A-102',{'allergies':['NSAIDs']})
        self.assertFalse(self.monitor.check_medication('A-102',{'medication':'ibuprofen'})['recording_allowed'])

    def test_allergy_checks_are_profile_specific_and_rechecked_at_recording(self):
        self.assertTrue(self.monitor.check_medication('A-102',{'medication':'amoxicillin'})['recording_allowed'])
        self.monitor.update_allergies('A-102',{'allergies':['amoxicillin']})
        with self.assertRaises(ValueError):self.monitor.record_medication('A-102',{'medication':'amoxicillin'})
        event=self.monitor.record_medication('A-101',{'medication':'paracetamol','note':'Manual test record'})
        self.assertEqual(event['medication'],'acetaminophen')
        self.assertEqual(self.monitor.snapshot('A-101')['alerts'],[])

    def test_matching_reported_exposure_changes_allergic_rule_assessment(self):
        snap=self.monitor.update_symptoms('A-101',{'symptoms':['visible_rash']})
        self.assertFalse(any(f['rule_id'] in {'C01','C02'} for f in snap['assessment']['findings']))
        snap=self.monitor.update_symptoms('A-101',{'reported_exposures':['amoxicillin']})
        finding=next(f for f in snap['assessment']['findings'] if f['rule_id']=='C01')
        self.assertTrue(finding['allergy_evidence'])
        snap=self.monitor.update_symptoms('A-101',{'symptoms':['acute_respiratory_distress']})
        self.assertTrue(any(f['rule_id']=='C02' and f['level']=='EMERGENCY' for f in snap['assessment']['findings']))
        other=self.monitor.update_symptoms('A-102',{'symptoms':['visible_rash'],'reported_exposures':['amoxicillin']})
        self.assertFalse(any(f['rule_id']=='C01' for f in other['assessment']['findings']))

    def test_allergy_history_alone_does_not_create_current_diagnosis(self):
        snap=self.monitor.snapshot('A-101')
        self.assertFalse(snap['assessment']['findings'])

    def test_macos_shortcut_is_a_native_application_wrapper(self):
        paths=install_macos(Path(self.temp.name)/'Desktop with spaces')
        bundle=paths[0]
        with (bundle/'Contents'/'Info.plist').open('rb') as source:info=plistlib.load(source)
        self.assertEqual(info['CFBundlePackageType'],'APPL')
        self.assertIn('launch_desktop.py',(bundle/'Contents'/'MacOS'/'AstroHealth').read_text())
        self.assertTrue((bundle/'Contents'/'MacOS'/'AstroHealth').stat().st_mode & 0o111)
        snap=self.monitor.update_symptoms('A-101',{'reported_exposures':['amoxicillin']})
        self.assertFalse(snap['assessment']['findings'])

    def test_allergy_edits_and_reported_exposures_persist(self):
        self.monitor.update_allergies('A-102',{'allergies':['cetirizine']})
        self.monitor.update_symptoms('A-102',{'reported_exposures':['cetirizine'],'symptoms':['visible_rash']})
        self.monitor.close()
        self.monitor=Monitor(Path(self.temp.name),ROOT/'config',ROOT/'profiles',clock=lambda:self.now)
        self.assertEqual(self.monitor.check_medication('A-102',{'medication':'cetirizine'})['status'],'blocked')
        self.assertTrue(any(f['rule_id']=='C01' for f in self.monitor.snapshot('A-102')['assessment']['findings']))

    def test_blocked_treatment_details_are_withheld_and_avoidance_remains_visible(self):
        guard=self.monitor.allergy_guard;profile=self.monitor.snapshot('A-101')['profile']
        entry=guard.treatment(profile,{'treatment_name':'Amoxicillin','instructions':['Take amoxicillin.'],'dosage':'Example source dose'})
        self.assertEqual(entry['allergy_safety']['status'],'blocked')
        self.assertFalse(entry['instructions'])
        self.assertIn('Withheld',entry['dosage'])
        profile['medical_history']['allergies']=['unlisted ingredient']
        entry=guard.treatment(profile,{'treatment_name':'Unlisted ingredient','instructions':['Take unlisted ingredient.'],'dosage':'Source amount'})
        self.assertEqual(entry['allergy_safety']['status'],'blocked')
        self.monitor.update_allergies('A-101',{'allergies':['midodrine']})
        entry=guard.treatment(self.monitor.snapshot('A-101')['profile'],{'treatment_name':'Avoid Midodrine','instructions':['Avoid midodrine.']})
        self.assertEqual(entry['allergy_safety']['status'],'avoidance_guidance')
        self.assertTrue(entry['instructions'])

    def test_startup_does_not_replay_stored_warnings_or_create_new_ones(self):
        self.monitor.import_lab('A-101',self.report())
        before=len(self.monitor.history('A-101')['events'])
        self.monitor.close();self.monitor=Monitor(Path(self.temp.name),ROOT/'config',ROOT/'profiles',clock=lambda:self.now)
        tracker=AlertTracker(self.monitor)
        for _ in range(3):self.monitor.tick();self.assertEqual(tracker.collect(self.monitor),[])
        self.assertEqual(len(self.monitor.history('A-101')['events']),before)
        self.assertTrue(self.monitor.snapshot('A-101')['alerts'])
        self.now+=timedelta(seconds=1)
        self.monitor.ingest('A-101',{'timestamp':self.now.isoformat(),'source':'jsonl','readings':{'heart_rate':{'value':72,'unit':'bpm'}}})
        self.assertEqual(tracker.collect(self.monitor),[])
        self.now+=timedelta(seconds=1)
        self.monitor.ingest('A-101',{'timestamp':self.now.isoformat(),'source':'jsonl','readings':{'spo2':{'value':89,'unit':'%'}}})
        self.assertTrue(tracker.collect(self.monitor));self.assertEqual(tracker.collect(self.monitor),[])

    def test_worsening_threshold_severity_generates_one_new_warning(self):
        tracker=AlertTracker(self.monitor)
        for value in [94,94,89]:
            self.now+=timedelta(seconds=1)
            self.monitor.ingest('A-101',{'timestamp':self.now.isoformat(),'source':'jsonl','readings':{'spo2':{'value':value,'unit':'%'}}})
            events=tracker.collect(self.monitor)
            if value==89:self.assertTrue(any(e['alert']['severity']=='URGENT' for e in events))
        self.assertEqual(tracker.collect(self.monitor),[])

    def test_intentional_simulation_stop_or_one_shot_does_not_raise_sensor_loss(self):
        sim=Simulator(self.monitor)
        sim.control('A-101',{'action':'once','mode':'normal'})
        self.now+=timedelta(seconds=61);self.monitor.tick()
        self.assertFalse(self.monitor.snapshot('A-101')['alerts'])
        sim.control('A-101',{'action':'start','mode':'normal'});sim.tick()
        sim.control('A-101',{'action':'stop'})
        self.now+=timedelta(seconds=61);self.monitor.tick()
        self.assertFalse(self.monitor.snapshot('A-101')['alerts'])


@unittest.skipUnless(os.environ.get('DISPLAY'),'Native Tk tests require a display/Xvfb')
class NativeWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from astrohealth.desktop import NativeApp
        self.temp=tempfile.TemporaryDirectory();self.monitor=Monitor(Path(self.temp.name),ROOT/'config',ROOT/'profiles')
        self.root=tk.Tk();self.root.withdraw();self.stop=threading.Event();self.queue=queue.Queue();self.show=threading.Event()
        self.app=NativeApp(self.root,self.monitor,Simulator(self.monitor),self.queue,self.stop,self.show)
        self.root.update()

    def tearDown(self):
        self.app.quit();self.monitor.close();self.temp.cleanup()

    def test_co2_hidden_until_read_and_native_widgets_remain_same(self):
        self.assertEqual(self.root.state(),'normal')
        self.assertFalse(self.app.live_tree.exists('cabin_co2'))
        combo=str(self.app.mode_combo);self.app.mode_var.set('High cabin CO₂')
        for _ in range(3):self.app.refresh();self.root.update()
        self.assertEqual(str(self.app.mode_combo),combo)
        self.assertEqual(self.app.mode_var.get(),'High cabin CO₂')
        self.app.simulate('once');self.root.update()
        self.assertTrue(self.app.live_tree.exists('cabin_co2'))

    def test_search_focus_query_and_selection_survive_refresh(self):
        self.app.tabs.select(self.app.frames['library']);self.app.library_search.set('epinephrine')
        self.app.library_entry.focus_force();self.root.update()
        count=self.app.library_list.size();self.assertGreater(count,0)
        for _ in range(3):self.app.refresh();self.root.update()
        self.assertEqual(self.app.library_search.get(),'epinephrine')
        self.assertEqual(self.root.focus_get(),self.app.library_entry)
        self.assertEqual(self.app.library_list.size(),count)
        self.app.library_search.set('xyzzymissing');self.assertEqual(self.app.library_list.size(),0)

    def test_open_simulation_dropdown_is_not_dismissed_by_refresh(self):
        combo=self.app.mode_combo
        self.root.tk.call('ttk::combobox::Post',str(combo));self.root.update()
        popdown=self.root.tk.call('ttk::combobox::PopdownWindow',str(combo))
        self.assertTrue(int(self.root.tk.call('winfo','ismapped',popdown)))
        self.app.refresh();self.root.update()
        self.assertTrue(int(self.root.tk.call('winfo','ismapped',popdown)))
        self.root.tk.call('ttk::combobox::Unpost',str(combo))

    def test_allergy_block_disables_record_button(self):
        self.app.med_var.set('amoxicillin');self.app.check_medication();self.root.update()
        self.assertEqual(str(self.app.record_button.cget('state')),'disabled')
        self.assertIn('BLOCKED',self.app.med_status.cget('text'))

    def test_background_warning_restores_native_window_without_browser(self):
        self.app.hide();self.root.update()
        self.queue.put({'aid':'A-101','alert':{'message':'New test warning'}})
        with patch('webbrowser.open') as browser:
            self.app.poll();self.root.update()
            browser.assert_not_called()
        self.assertEqual(self.root.state(),'normal')


if __name__=='__main__':unittest.main()
