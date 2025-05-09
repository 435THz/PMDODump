import os
import shutil

import httplib2
import xml.etree.ElementTree as ET
import glob
import time
from apiclient import discovery
from sheetMerge import SheetMerge

SHEET_CONTENT_START = 2
WAIT_TIME = 3

class ItemGen(SheetMerge):
    """
    A class for syncronizing the strings in the project files
    with the google doc spreadsheets containing translations.
    """
    def __init__(self, credentials, id):
        super().__init__(credentials, id, SHEET_CONTENT_START)


    def write_data_text(self, txt_name, sheet_name):
        """
        Writes data from a txt to the sheet
        """
        header, table = self._query_txt(os.path.join("..", "DataAsset", "Item", txt_name+".txt"))
        # merge the data together, back into the google sheets
        self._write_sheet_table(sheet_name, table)

    def load_sheet_text(self, txt_name, sheet_name):
        """
        Loads sheet text and writes it to txt file.
        """
        header_row, sheet = self._query_sheet(sheet_name)

        self._write_txt(os.path.join("..", "DataAsset", "Item", txt_name + ".out.txt"), header_row, sheet)


    def merge_data_text(self, txt_name, sheet_name):
        """
        Merges together the specified mons in the data sheet with the mons in the txt
        """
        # the google sheet needs family numbers (first dex in the group)
        # it also needs individual dex numbers
        header_row, sheet = self._query_sheet(sheet_name)
        # load data from translation table file
        tbl_path = os.path.join("..", "DataAsset", "Item", txt_name+".txt")
        _, table = self._query_txt(os.path.join("..", "DataAsset", "Item", txt_name+".txt"))
        prev_table = []
        prev_path = os.path.join("..", "DataAsset", "Item", txt_name+"_prev.txt")
        if os.path.exists(prev_path):
            _, prev_table = self._query_txt(prev_path)
        # merge the data together, back into the google sheets
        new_prev_table = self._merge_sheet_table(sheet_name, sheet, table, prev_table)

        self._write_txt(prev_path, header_row, new_prev_table)

    def _sheet_format(self, table):
        # fill in user, evo, index, rarity.
        # ON should be false by default.
        # Generic Name should be 0* None
        # Trade should be *
        # Effect should be 000: None

        new_table = []
        for row in table:
            new_row = ["0* None", "", row[1], row[0], "FALSE", row[2], "", "", "", "", row[3], row[4], row[5],
                      "000: None", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
            new_table.append(new_row)

        return new_table

    def _get_family_dict(self, sheet):

        new_dict = {}
        for row in sheet:
            family_id = int(row[3])
            if family_id not in new_dict:
                new_dict[family_id] = []
            new_dict[family_id].append(row.copy())
        return new_dict

    def _get_family_diff(self, f1, f2):

        has_diff = False
        name_diff = []

        for ii in range(max(len(f1), len(f2))):
            if ii < len(f1) and ii < len(f2):
                if f1[ii] != f2[ii]:
                    has_diff = True
                name_diff.append((f1[ii], f2[ii]))
            elif ii < len(f1):
                has_diff = True
                name_diff.append((f1[ii], ""))
            else:
                has_diff = True
                name_diff.append(("", f2[ii]))

        if has_diff:
            return name_diff
        return None

    def _get_existing_families(self, remote_families, min_species):

        existing_families = []
        for species in remote_families:
            for row in remote_families[species]:
                if row[2] in min_species:
                    existing_families.append(species)
                    break

        return existing_families

    def _merge_sheet_table(self, sheet_name, sheet, table, prev_table):
        """
        Takes the array of exclusive items from google sheets,
        and merges it with the array of exclusive items from the local copy.
        It writes directly to the remote google sheet, and can only add/edit.  No deletes.
        """
        # create a dictionary that maps family dex number to group
        remote_families = self._get_family_dict(sheet)
        local_families = self._get_family_dict(self._sheet_format(table))
        prev_families = self._get_family_dict(prev_table)

        # only diffs will be processed
        changed_families = {}
        for species in local_families:
            if species not in prev_families:
                changed_families[species] = local_families[species]
                continue
            prev_col = [r[2] for r in prev_families[species]]
            local_col = [r[2] for r in local_families[species]]
            family_diff = self._get_family_diff(prev_col, local_col)
            if family_diff is not None:
                changed_families[species] = local_families[species]

        cmb_families = self._get_family_dict(sheet)
        # add the changed_families's values into cmb_families
        deferred_families = []
        for species in changed_families:
            local_col = [r[2] for r in changed_families[species]]
            if species not in cmb_families:
                # if the family is new, but some members are in an existing group, ask if it should be added
                min_species = []
                for family_species in local_col:
                    if family_species not in min_species:
                        min_species.append(family_species)
                existing_families = self._get_existing_families(remote_families, min_species)
                if len(existing_families) > 0:
                    family_str = ", ".join(min_species)
                    existing_str = ", ".join([str(a) for a in existing_families])
                    overwrite = input("New family {0} has {1}, which already exist in families {2}.\nDo you want to add it? y/n/(d)\n".format(species, family_str, existing_str))
                    if overwrite.lower() != 'y':
                        if overwrite.lower() != 'n':
                            deferred_families.append(species)
                        continue
                cmb_families[species] = changed_families[species]
                continue
            cur_col = [r[2] for r in cmb_families[species]]
            family_diff = self._get_family_diff(cur_col, local_col)
            if family_diff is not None:
                family_diff_rows = ["{0}\t->\t{1}".format(a[0], a[1]) for a in family_diff]
                family_diff_str = "\n".join(family_diff_rows)
                # if the user sequence is different, ask if the new one should overwrite the old one
                overwrite = input("Family {0} has changed:\n{1}\nAdopt these changes? y/n/(d)\n".format(species, family_diff_str))
                if overwrite.lower() != 'y':
                    if overwrite.lower() != 'n':
                        deferred_families.append(species)
                    continue
                for idx, row in enumerate(changed_families[species]):
                    if idx < len(cmb_families[species][idx]):
                        old_row = cmb_families[species][idx]
                        old_row[2] = row[2]
                    else:
                        cmb_families[species][idx].append(row)


        # afterwards, save the EvoTreeRef.txt as a _prev file,
        # so the next time you run this operation, only diffs will be processed
        new_prev = []
        for species in local_families:
            if species not in deferred_families:
                group = local_families[species]
                for row in group:
                    new_prev.append(row)


        # create a list of the combined keys
        cmb_keys = []
        for species in cmb_families:
            cmb_keys.append(species)

        # sort the keys properly
        cmb_keys = sorted(cmb_keys)

        resp = self._service.spreadsheets().get(spreadsheetId=self._id, ranges=sheet_name).execute()

        if len(resp['sheets']) != 1:
            raise ValueError("Could not find unambiguous sheet " + sheet_name)
        else:
            sheet_id = resp['sheets'][0]['properties']['sheetId']

        sheet_ind = SHEET_CONTENT_START
        for cmb_key in cmb_keys:
            group = cmb_families[cmb_key]
            remote_group = None
            if cmb_key in remote_families:
                remote_group = remote_families[cmb_key]

            for idx, row in enumerate(group):

                # remote_group does not exist? insert all rows and populate
                # row of cmb_group does not exist in remote_group? insert row and populate
                diff = False
                if remote_group is None or idx >= len(remote_group):
                    body = { "insertDimension": { "range": { "sheetId": sheet_id, "dimension": "ROWS", "startIndex": sheet_ind-1, "endIndex": sheet_ind } } }
                    self._service.spreadsheets().batchUpdate(spreadsheetId=self._id, body={'requests': [body]}).execute()
                    diff = True
                else:
                    remote_row = remote_group[idx]
                    for col_idx in range(len(row)):
                        if row[col_idx] != remote_row[col_idx]:
                            diff = True
                            break

                # row of cmb_group is different from row of remote_group? update
                if diff:
                    range_name = sheet_name + "!"+str(sheet_ind)+":"+str(sheet_ind)
                    row[8] = "=IF(A{0} = \"0* None\",B{0},CONCAT(C{0}, MID(A{0}, 3, 100)))".format(sheet_ind)
                    row[9] = "=IF(G{0} = \"\",IF(F{0},CONCAT(C{0},\"'s Family\"),C{0}),G{0})".format(sheet_ind)

                    body = { 'values': [row] }
                    self._service.spreadsheets().values().update(spreadsheetId=self._id, range=range_name, valueInputOption="USER_ENTERED", body=body).execute()
                    time.sleep(WAIT_TIME)

                sheet_ind += 1
                if (sheet_ind - SHEET_CONTENT_START) % 100 == 0:
                    print(str(sheet_ind - SHEET_CONTENT_START) + " merged")

            # cmb_group does not exist?  impossible: cmb_families is a superset of remote_families
            # row of remote_group does not exist in cmb_group? delete row
            idx = len(group)
            if remote_group is not None:
                while idx < len(remote_group):
                    body = { "deleteDimension": { "range": { "sheetId": sheet_id, "dimension": "ROWS", "startIndex": sheet_ind-1, "endIndex": sheet_ind } } }
                    self._service.spreadsheets().batchUpdate(spreadsheetId=self._id, body={'requests': [body]}).execute()
                    idx += 1

        return new_prev


