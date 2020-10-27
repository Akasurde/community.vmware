#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2018, Abhijeet Kasurde <akasurde@redhat.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


DOCUMENTATION = r'''
---
module: vcenter_folder
short_description: Manage folders on given datacenter
description:
- This module can be used to create, delete, move and rename folder on then given datacenter.
- This module is only supported for vCenter.
author:
- Abhijeet Kasurde (@Akasurde)
- Christian Kotte (@ckotte) <christian.kotte@gmx.de>
- Jan Meerkamp (@meerkampdvv)
notes:
- Tested on vSphere 6.5
requirements:
- python >= 2.6
- PyVmomi
options:
  datacenter:
    description:
    - Name of the datacenter.
    required: True
    aliases: ['datacenter_name']
    type: str
  folder_name:
    description:
    - Name of folder to be managed.
    - This is case sensitive parameter.
    - Folder name should be under 80 characters. This is a VMware restriction.
    required: True
    type: str
  parent_folder:
    description:
    - Name of the parent folder under which new folder needs to be created.
    - This is case sensitive parameter.
    - "If user wants to create a folder under '/DC0/vm/vm_folder', this value will be 'vm_folder'."
    - "If user wants to create a folder under '/DC0/vm/folder1/folder2', this value will be 'folder1/folder2'."
    - This is required if C(parent_folder_moid) is not specified when addressing a parent folder.
    required: False
    type: str
  parent_folder_moid:
    description:
    - Managed object ID of the parent folder.
    - This parameter is useful while identifying non-unique or nested folder objects.
    - This is required if C(parent_folder) is not specified when addressing a parent folder.
    required: False
    type: str
    version_added: '1.4.0'
  folder_type:
    description:
    - This is type of folder.
    - "If set to C(vm), then 'VM and Template Folder' is created under datacenter."
    - "If set to C(host), then 'Host and Cluster Folder' is created under datacenter."
    - "If set to C(datastore), then 'Storage Folder' is created under datacenter."
    - "If set to C(network), then 'Network Folder' is created under datacenter."
    - This parameter is required, if C(state) is set to C(present) and parent_folder is absent.
    - This option is ignored, if C(parent_folder) is set.
    default: vm
    type: str
    required: False
    choices: [ datastore, host, network, vm ]
  state:
    description:
    - State of folder.
    - If set to C(present) without parent folder parameter, then folder with C(folder_type) is created.
    - If set to C(present) with parent folder parameter,  then folder in created under parent folder. C(folder_type) is ignored.
    - If set to C(absent), then folder is unregistered and destroyed.
    default: present
    choices: [ present, absent ]
    type: str
extends_documentation_fragment:
- community.vmware.vmware.documentation

'''

EXAMPLES = r'''
- name: Create a VM folder on given datacenter
  community.vmware.vcenter_folder:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    datacenter_name: datacenter_name
    folder_name: sample_vm_folder
    folder_type: vm
    state: present
  register: vm_folder_creation_result
  delegate_to: localhost

- name: Create a datastore folder on given datacenter
  community.vmware.vcenter_folder:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    datacenter_name: datacenter_name
    folder_name: sample_datastore_folder
    folder_type: datastore
    state: present
  register: datastore_folder_creation_result
  delegate_to: localhost

- name: Create a sub folder under VM folder on given datacenter
  community.vmware.vcenter_folder:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    datacenter_name: datacenter_name
    folder_name: sample_sub_folder
    parent_folder: vm_folder
    state: present
  register: sub_folder_creation_result
  delegate_to: localhost

- name: Delete a VM folder on given datacenter
  community.vmware.vcenter_folder:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    datacenter_name: datacenter_name
    folder_name: sample_vm_folder
    folder_type: vm
    state: absent
  register: vm_folder_deletion_result
  delegate_to: localhost

# MoID
- name: Get folder info
  community.vmware.vmware_folder_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    validate_certs: no
    datacenter: Asia-Datacenter1
  register: folder_info

- set_fact:
    parent_folder_moid: "{{ (folder_info['flat_folder_info'] | selectattr('path', 'search', '/vm/tier1/tier2') | map(attribute='moid'))[0] }}"

- name: Create tier3 folder under tier1/tier2
  community.vmware.vcenter_folder:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    validate_certs: no
    datacenter: Asia-Datacenter1
    folder_name: tier3
    parent_folder_moid: '{{ parent_folder_moid }}'
    folder_type: vm
    state: present
'''

RETURN = r'''
result:
    description: The detail about the new folder
    returned: On success
    type: complex
    contains:
        path:
            description: the full path of the new folder
            type: str
        msg:
            description: string stating about result
            type: str
'''

try:
    from pyVmomi import vim, VmomiSupport, vmodl
except ImportError:
    pass

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.vmware.plugins.module_utils.vmware import vmware_argument_spec, PyVmomi, find_datacenter_by_name, wait_for_task, get_all_objs
from ansible.module_utils._text import to_native


class VmwareFolderManager(PyVmomi):
    def __init__(self, module):
        super(VmwareFolderManager, self).__init__(module)
        datacenter_name = self.params.get('datacenter', None)
        self.datacenter_obj = find_datacenter_by_name(self.content, datacenter_name=datacenter_name)
        if self.datacenter_obj is None:
            self.module.fail_json(msg="Failed to find datacenter %s" % datacenter_name)

        self.datacenter_folder_type = {
            'vm': self.datacenter_obj.vmFolder,
            'host': self.datacenter_obj.hostFolder,
            'datastore': self.datacenter_obj.datastoreFolder,
            'network': self.datacenter_obj.networkFolder,
        }

    def ensure(self):
        """
        Manage internal state management
        """
        state = self.module.params.get('state')
        datacenter_name = self.module.params.get('datacenter')
        folder_type = self.module.params.get('folder_type')
        folder_name = self.module.params.get('folder_name')
        parent_folder = self.module.params.get('parent_folder', None)
        parent_folder_moid = self.module.params.get('parent_folder_moid', None)

        results = {'changed': False, 'result': {}}
        if state == 'present':
            # Check if the folder already exists
            p_folder_obj = None
            if parent_folder_moid:
                p_folder_obj = VmomiSupport.templateOf('Folder')(parent_folder_moid, self.si._stub)
                try:
                    parent_folder = p_folder_obj.name
                except vmodl.fault.ManagedObjectNotFound as e:
                    self.module.fail_json(msg="Could not find folder using moid %s : %s" % (parent_folder_moid, to_native(e)))
                child_folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                                   folder_name=folder_name,
                                                   folder_type=folder_type,
                                                   parent_folder=p_folder_obj)
                if child_folder_obj:
                    results['result'] = "Folder %s already exists under" \
                                        " parent folder %s" % (folder_name, parent_folder)
                    self.module.exit_json(**results)
            elif parent_folder:
                if "/" in parent_folder:
                    parent_folder_parts = parent_folder.strip('/').split('/')
                    p_folder_obj = None
                    for part in parent_folder_parts:
                        part_folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                                          folder_name=part,
                                                          folder_type=folder_type,
                                                          parent_folder=p_folder_obj)
                        if not part_folder_obj:
                            self.module.fail_json(msg="Could not find folder %s" % part)
                        p_folder_obj = part_folder_obj
                    child_folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                                       folder_name=folder_name,
                                                       folder_type=folder_type,
                                                       parent_folder=p_folder_obj)
                    if child_folder_obj:
                        results['result'] = "Folder %s already exists under" \
                                            " parent folder %s" % (folder_name, parent_folder)
                        self.module.exit_json(**results)
                else:
                    p_folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                                   folder_name=parent_folder,
                                                   folder_type=folder_type)

                    if not p_folder_obj:
                        self.module.fail_json(msg="Parent folder %s does not exist" % parent_folder)

                    # Check if folder exists under parent folder
                    child_folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                                       folder_name=folder_name,
                                                       folder_type=folder_type,
                                                       parent_folder=p_folder_obj)
                    if child_folder_obj:
                        results['result']['path'] = self.get_folder_path(child_folder_obj)
                        results['result'] = "Folder %s already exists under" \
                                            " parent folder %s" % (folder_name, parent_folder)
                        self.module.exit_json(**results)
            else:
                folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                             folder_name=folder_name,
                                             folder_type=folder_type)

                if folder_obj:
                    results['result']['path'] = self.get_folder_path(folder_obj)
                    results['result']['msg'] = "Folder %s already exists" % folder_name
                    self.module.exit_json(**results)

            # Create a new folder
            try:
                if (parent_folder or parent_folder_moid) and p_folder_obj:
                    if parent_folder_moid:
                        parent_folder = p_folder_obj.name
                    if self.module.check_mode:
                        results['msg'] = "Folder '%s' of type '%s' under '%s' will be created." % \
                                         (folder_name, folder_type, parent_folder)
                    else:
                        new_folder = p_folder_obj.CreateFolder(folder_name)
                        results['result']['path'] = self.get_folder_path(new_folder)
                        results['result']['msg'] = "Folder '%s' of type '%s' under '%s' created" \
                            " successfully." % (folder_name, folder_type, parent_folder)
                    results['changed'] = True
                elif not parent_folder and not p_folder_obj:
                    if self.module.check_mode:
                        results['msg'] = "Folder '%s' of type '%s' will be created." % (folder_name, folder_type)
                    else:
                        new_folder = self.datacenter_folder_type[folder_type].CreateFolder(folder_name)
                        results['result']['msg'] = "Folder '%s' of type '%s' created successfully." % (folder_name, folder_type)
                        results['result']['path'] = self.get_folder_path(new_folder)
                    results['changed'] = True
            except vim.fault.DuplicateName as duplicate_name:
                # To be consistent with the other vmware modules, We decided to accept this error
                # and the playbook should simply carry on with other tasks.
                # User will have to take care of this exception
                # https://github.com/ansible/ansible/issues/35388#issuecomment-362283078
                results['changed'] = False
                results['msg'] = "Failed to create folder as another object has same name" \
                                 " in the same target folder : %s" % to_native(duplicate_name.msg)
            except vim.fault.InvalidName as invalid_name:
                self.module.fail_json(msg="Failed to create folder as folder name is not a valid "
                                          "entity name : %s" % to_native(invalid_name.msg))
            except Exception as general_exc:
                self.module.fail_json(msg="Failed to create folder due to generic"
                                          " exception : %s " % to_native(general_exc))
            self.module.exit_json(**results)
        elif state == 'absent':
            # Check if the folder already exists
            p_folder_obj = None
            if parent_folder_moid:
                p_folder_obj = VmomiSupport.templateOf('Folder')(parent_folder_moid, self.si._stub)
                try:
                    parent_folder = p_folder_obj.name
                except vmodl.fault.ManagedObjectNotFound as e:
                    self.module.fail_json(msg="Could not find folder using moid %s : %s" % (parent_folder_moid, to_native(e)))
                folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                             folder_name=folder_name,
                                             folder_type=folder_type,
                                             parent_folder=p_folder_obj)
            elif parent_folder:
                if "/" in parent_folder:
                    parent_folder_parts = parent_folder.strip('/').split('/')
                    p_folder_obj = None
                    for part in parent_folder_parts:
                        part_folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                                          folder_name=part,
                                                          folder_type=folder_type,
                                                          parent_folder=p_folder_obj)
                        if not part_folder_obj:
                            self.module.fail_json(msg="Could not find folder %s" % part)
                        p_folder_obj = part_folder_obj
                    folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                                 folder_name=folder_name,
                                                 folder_type=folder_type,
                                                 parent_folder=p_folder_obj)
                else:
                    p_folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                                   folder_name=parent_folder,
                                                   folder_type=folder_type)

                    if not p_folder_obj:
                        self.module.fail_json(msg="Parent folder %s does not exist" % parent_folder)

                    # Check if folder exists under parent folder
                    folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                                 folder_name=folder_name,
                                                 folder_type=folder_type,
                                                 parent_folder=p_folder_obj)
            else:
                folder_obj = self.get_folder(datacenter_name=datacenter_name,
                                             folder_name=folder_name,
                                             folder_type=folder_type)
            if folder_obj:
                try:
                    if parent_folder:
                        if self.module.check_mode:
                            results['changed'] = True
                            results['msg'] = "Folder '%s' of type '%s' under '%s' will be removed." % \
                                             (folder_name, folder_type, parent_folder)
                        else:
                            if folder_type == 'vm':
                                task = folder_obj.UnregisterAndDestroy()
                            else:
                                task = folder_obj.Destroy()
                            results['changed'], results['msg'] = wait_for_task(task=task)
                    else:
                        if self.module.check_mode:
                            results['changed'] = True
                            results['msg'] = "Folder '%s' of type '%s' will be removed." % (folder_name, folder_type)
                        else:
                            if folder_type == 'vm':
                                task = folder_obj.UnregisterAndDestroy()
                            else:
                                task = folder_obj.Destroy()
                            results['changed'], results['msg'] = wait_for_task(task=task)
                except vim.fault.ConcurrentAccess as concurrent_access:
                    self.module.fail_json(msg="Failed to remove folder as another client"
                                              " modified folder before this operation : %s" % to_native(concurrent_access.msg))
                except vim.fault.InvalidState as invalid_state:
                    self.module.fail_json(msg="Failed to remove folder as folder is in"
                                              " invalid state : %s" % to_native(invalid_state.msg))
                except Exception as gen_exec:
                    self.module.fail_json(msg="Failed to remove folder due to generic"
                                              " exception %s " % to_native(gen_exec))
            self.module.exit_json(**results)

    def get_folder(self, datacenter_name, folder_name, folder_type, parent_folder=None):
        """
        Get managed object of folder by name
        Returns: Managed object of folder by name

        """
        folder_objs = get_all_objs(self.content, [vim.Folder], parent_folder)
        for folder in folder_objs:
            if parent_folder:
                if folder.name == folder_name and \
                   self.datacenter_folder_type[folder_type].childType == folder.childType:
                    return folder
            else:
                if folder.name == folder_name and \
                   self.datacenter_folder_type[folder_type].childType == folder.childType and \
                   folder.parent.parent.name == datacenter_name:    # e.g. folder.parent.parent.name == /DC01/host/folder
                    return folder

        return None


def main():
    argument_spec = vmware_argument_spec()
    argument_spec.update(
        datacenter=dict(type='str', required=True, aliases=['datacenter_name']),
        folder_name=dict(type='str', required=True),
        parent_folder=dict(type='str', required=False),
        parent_folder_moid=dict(type='str', required=False),
        state=dict(type='str',
                   choices=['present', 'absent'],
                   default='present'),
        folder_type=dict(type='str',
                         default='vm',
                         choices=['datastore', 'host', 'network', 'vm'],
                         required=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        mutually_exclusive=[
            ['parent_folder', 'parent_folder_moid'],
        ],
    )

    if len(module.params.get('folder_name')) > 79:
        module.fail_json(msg="Failed to manage folder as folder_name can only contain 80 characters.")

    vcenter_folder_mgr = VmwareFolderManager(module)
    if not vcenter_folder_mgr.is_vcenter():
        module.fail_json(msg="Module vcenter_folder is meant for vCenter, hostname %s "
                             "is not vCenter server." % module.params.get('hostname'))
    vcenter_folder_mgr.ensure()


if __name__ == "__main__":
    main()
