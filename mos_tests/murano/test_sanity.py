#    Copyright 2016 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging
import types
import uuid

from muranodashboard.tests.functional import base
from muranodashboard.tests.functional.config import config as cfg
from muranodashboard.tests.functional import consts as c
import pytest
from selenium.webdriver.common import by
from selenium.webdriver.support import ui
from xvfbwrapper import Xvfb

from mos_tests import settings

logger = logging.getLogger(__name__)


@pytest.yield_fixture(scope='class')
def screen():
    vdisplay = Xvfb()
    vdisplay.start()
    yield
    vdisplay.stop()


def murano_test_patch(cls):
    """Class decorator to make setUpClass method lazy"""

    def lazySetUpClass(cls):  # noqa
        return super(cls, cls).setUpClass()

    def setUpClass(cls):
        pass

    @pytest.fixture(scope="class", autouse=True)
    def set_config(self, credentials):
        cfg.common.horizon_url = 'http://{0.controller_ip}/horizon'.format(
            credentials)
        cfg.common.user = credentials.username
        cfg.common.password = credentials.password
        cfg.common.tenant = credentials.project
        cfg.common.keystone_url = credentials.keystone_url
        cfg.common.murano_url = 'http://{0.controller_ip}:8082/'.format(
            credentials)
        cfg.common.ca_cert = credentials.cert
        self.lazySetUpClass()

    def switch_to_project(self, name):
        pass

    if 'setUpClass' in cls.__dict__:
        method = cls.setUpClass
    else:
        method = types.MethodType(lazySetUpClass, cls, cls)
    setattr(cls, 'lazySetUpClass', method)
    setattr(cls, 'setUpClass', types.MethodType(setUpClass, cls, cls))
    setattr(cls, 'set_config', set_config)
    setattr(cls, 'switch_to_project', switch_to_project)

    return cls


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.undestructive
@pytest.mark.usefixtures('screen')
@murano_test_patch
class TestImportPackageWithDepencies(base.PackageTestCase):

    def tearDown(self):
        for pkg in self.murano_client.packages.list():
            if pkg.name in settings.MURANO_PACKAGE_DEPS_NAMES:
                self.murano_client.packages.delete(pkg.id)
        super(TestImportPackageWithDepencies, self).tearDown()

    def test_import_package_by_url(self):
        """Test package importing via url."""

        self.navigate_to('Manage')
        self.go_to_submenu('Package Definitions')
        self.driver.find_element_by_id(c.UploadPackage).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_url")

        el = self.driver.find_element_by_css_selector(
            "input[name='upload-url']")
        el.send_keys(settings.MURANO_PACKAGE_WITH_DEPS_URL)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        for el in self.driver.find_elements_by_class_name('alert'):
            el.find_element_by_class_name('close').click()

        # No application data modification is needed
        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()
        for pkg_name in settings.MURANO_PACKAGE_DEPS_NAMES:
            self.check_element_on_page(
                by.By.XPATH, c.AppPackages.format(pkg_name))

    def test_import_package_from_repo(self):
        """Test package importing via fqn from repo with dependent apps."""

        self.navigate_to('Manage')
        self.go_to_submenu('Package Definitions')
        self.driver.find_element_by_id(c.UploadPackage).click()
        sel = self.driver.find_element_by_css_selector(
            "select[name='upload-import_type']")
        sel = ui.Select(sel)
        sel.select_by_value("by_name")

        el = self.driver.find_element_by_css_selector(
            "input[name='upload-repo_name']")
        el.send_keys(settings.MURANO_PACKAGE_WITH_DEPS_FQN)
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        for el in self.driver.find_elements_by_class_name('alert'):
            el.find_element_by_class_name('close').click()

        self.driver.find_element_by_xpath(c.InputSubmit).click()
        self.driver.find_element_by_xpath(c.InputSubmit).click()

        self.wait_for_alert_message()

        for pkg_name in settings.MURANO_PACKAGE_DEPS_NAMES:
            self.check_element_on_page(
                by.By.XPATH, c.AppPackages.format(pkg_name))


@pytest.mark.requires_('firefox', 'xvfb-run')
@pytest.mark.undestructive
@pytest.mark.usefixtures('screen')
@murano_test_patch
class TestDeployEnvInNetwork(base.ApplicationTestCase):
    @classmethod
    def _create_network_with_subnet(cls, net_name, subnet_name,
                                    cidr=None):
        """Create network with subnet."""
        if cidr is None:
            cidr = '192.168.1.0/24'

        network = cls.os_conn.create_network(name=net_name)
        subnet = cls.os_conn.create_subnet(
            network_id=network['network']['id'],
            name=subnet_name,
            cidr=cidr,
            dns_nameservers=['8.8.8.8'])
        return network, subnet

    @classmethod
    def _create_router_between_nets(cls, router_name, ext_net, subnet):
        """Create router between external network and sub network."""
        router = cls.os_conn.create_router(name=router_name)
        cls.os_conn.router_gateway_add(
            router_id=router['router']['id'],
            network_id=ext_net['id'])

        cls.os_conn.router_interface_add(
            router_id=router['router']['id'],
            subnet_id=subnet['subnet']['id'])
        return router

    @staticmethod
    def gen_random_resource_name(prefix=None, reduce_by=None):
        random_name = str(uuid.uuid4()).replace('-', '')[::reduce_by]
        if prefix:
            random_name = prefix + '_' + random_name
        return random_name

    @classmethod
    @pytest.fixture(scope='class')
    def prepare(cls, os_conn_for_unittests):
        cls.net_name = cls.gen_random_resource_name(prefix='net')
        cls.subnet_name = cls.gen_random_resource_name(prefix='subnet')
        cls.router_name = cls.gen_random_resource_name(prefix='router')

        _, subnet = cls._create_network_with_subnet(
            net_name=cls.net_name,
            subnet_name=cls.subnet_name)

        cls._create_router_between_nets(
            router_name=cls.router_name,
            ext_net=cls.os_conn.ext_network,
            subnet=subnet)

    @classmethod
    def tearDownClass(cls):
        cls.os_conn.cleanup_network()
        super(TestDeployEnvInNetwork, cls).tearDownClass()
