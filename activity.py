# Copyright (c) 2010 Anish Mangal <anish@sugarlabs.org>
#
# If you find this useful, don't hesitate to send me the biggest
# telescope you can get your hands on;-)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

""" XoScope activity: A fun activity to use with a telescope :-) """

import logging
from gettext import gettext as _
from fcntl import ioctl
import time
import os
from xml.dom import minidom, Node

from color import Color

import gtk
import gobject
import pygst
pygst.require('0.10')
import gst
import v4l2

from sugar.activity import activity
from sugar.activity.activity import ActivityToolbox
from sugar.graphics.toolbutton import ToolButton
from sugar.graphics.tray import TrayButton
from sugar.graphics.palette import Palette
from sugar.datastore import datastore

OLD_TOOLBAR = False

try:
    # >= 0.86 toolbars
    from sugar.graphics.toolbarbox import ToolbarButton, ToolbarBox
    from sugar.activity.widgets import ActivityToolbarButton
    from sugar.activity.widgets import StopButton
except ImportError:
    # <= 0.84 toolbars
    OLD_TOOLBAR = True

VD = open('/dev/video0','rw')

class ScalePalette(Palette):

    def __init__(self, primary_text, v4l2_control = False,
            v4l2_auto_control = False):
        Palette.__init__(self, label=primary_text)

        vbox = gtk.VBox()
        self.set_content(vbox)
        vbox.show()

        if v4l2_control:
            self._query_control = v4l2.v4l2_queryctrl(v4l2_control)
            self._control = v4l2.v4l2_control(v4l2_control)

            ioctl(VD, v4l2.VIDIOC_QUERYCTRL, self._query_control)
            ioctl(VD, v4l2.VIDIOC_G_CTRL, self._control)

            _max = self._query_control.maximum
            _min = self._query_control.minimum

            if v4l2_control == v4l2.V4L2_CID_EXPOSURE:
                _min = 0
                _max = 512
            elif v4l2_control == v4l2.V4L2_CID_GAIN:
                _min = 0
                _max = 37
            elif v4l2_control == v4l2.V4L2_CID_CONTRAST:
                _min = 0
                _max = 127
            elif v4l2_control == v4l2.V4L2_CID_BRIGHTNESS:
                _min = 0
                _max = 255
            #elif v4l2_control == v4l2.V4L2_CID_NIGHT_MODE:
            #    _min = 0
            #    _max = 1

            self._adjustment = gtk.Adjustment(value=self._control.value,
                    lower=_min,
                    upper=_max,
                    step_incr=1, page_incr=1, page_size=0)

            self._hscale = gtk.HScale(self._adjustment)
            self._hscale.set_digits(0)
            self._hscale.set_draw_value(False)
            self._hscale.set_update_policy(gtk.UPDATE_DISCONTINUOUS)
            vbox.add(self._hscale)
            self._hscale.show()

            self._adjustment_handler_id = \
                self._adjustment.connect('value_changed',
                                         self.__adjustment_changed_cb)

            if v4l2_auto_control:
                self._auto_query_control =\
                    v4l2.v4l2_queryctrl(v4l2_auto_control)
                self._auto_control = v4l2.v4l2_control(v4l2_auto_control)

                self._auto_button = gtk.CheckButton('Auto')
                self._auto_button.set_active(self._auto_control.value)
                self._auto_button.connect('toggled',
                        self.__auto_button_toggled_cb)
                vbox.add(self._auto_button)
                self._auto_button.show()

                if self._auto_control.value == True:
                    self._hscale.set_sensitive(False)

        vbox.show()

    def __palette_clicked_cb(self, gobject):
        self.popup(immediate=True)

    def __auto_button_toggled_cb(self, checkbutton):
        self._auto_control.value = self._auto_button.get_active()
        ioctl(VD, v4l2.VIDIOC_S_CTRL, self._auto_control)

        if self._auto_control.value == True:
            self._hscale.set_sensitive(False)
        else:
            self._hscale.set_sensitive(True)

    def __adjustment_changed_cb(self, adj_):
        self._control.value = int(self._adjustment.value)
        ioctl(VD, v4l2.VIDIOC_S_CTRL, self._control)

class XoScopeActivity(activity.Activity):
    """XoScopeActivity class as specified in activity.info"""

    def __init__(self, handle):
        """Set up the XoScope activity."""
        activity.Activity.__init__(self, handle)

        self._instance_directory = os.path.join(self.get_activity_root(),\
                'instance')

        # we do not have collaboration features
        # make the share option insensitive
        self.max_participants = 1
        self._capturing = False
        self._mode = 'live'

        # 0, 2 or 5 second delay before capturing the image
        self._delay = 0

        # Zoom 1x, 2x, 4x
        self._zoom = 1

        # Exposure bracketing
        self._bracketing = '0'

        # Preview mode stuff
        self._num_pics = 0

        # Index of pic to be displayed in preview mode
        self._pic_index = 0

        # This holds the image titles and name information. Saved
        # across activity instances
        self._images = []

        # Flag to store whether image preview element needs to resize
        # the pixbuf
        self._needs_resize = False

        if OLD_TOOLBAR:
            self.toolbox = ActivityToolbox(self)
            self.set_toolbox(self.toolbox)
            self.toolbox.show()

            activity_toolbar = self.toolbox.get_activity_toolbar()
            activity_toolbar = gtk.Toolbar()
            self.toolbox.add_toolbar(_('Control'), activity_toolbar)
            self.toolbox.set_current_toolbar(1)
            self._controls_toolbar = activity_toolbar

            advanced_toolbar = self.toolbox.get_activity_toolbar()
            advanced_toolbar = gtk.Toolbar()
            #self.toolbox.add_toolbar(_('Advanced controls'), advanced_toolbar)
        else:
            toolbar_box = ToolbarBox()
            self.activity_button = ActivityToolbarButton(self)
            toolbar_box.toolbar.insert(self.activity_button, 0)
            self.activity_button.show()
            self.set_toolbar_box(toolbar_box)

            toolbar_box.show()
            activity_toolbar = self.activity_button.page
            self._controls_toolbar = self.get_toolbar_box().toolbar
            self._controls_toolbar.show()

            advanced_toolbar = gtk.Toolbar()
            #advanced_toolbar.show_all()
            advanced_button = ToolbarButton()
            advanced_button.props.page = advanced_toolbar
            advanced_button.props.label = _('Advanced controls')
            advanced_button.props.icon_name = 'advanced'
            #advanced_button.show()
            #toolbar_box.toolbar.insert(advanced_button, -1)

        self._live_toolitem = gtk.ToolItem()
        self._live_toolbar_container = gtk.HBox()

        self._preview_toolitem = gtk.ToolItem()
        self._preview_toolbar_container = gtk.HBox()

        separator = gtk.SeparatorToolItem()
        if not OLD_TOOLBAR:
            separator.props.draw = True
        else:
            separator.props.draw = False
        separator.set_expand(False)
        self._controls_toolbar.insert(separator, -1)
        separator.show()

        self._photo_button = ToolButton('photo')
        self._photo_button.props.label = _('Capture photo')
        self._photo_button.connect('clicked',
                self.__capture_image_cb)
        self._live_toolbar_container.add(self._photo_button)
        self._photo_button.show()

        self._delay_button = ToolButton('delay_%d' % self._delay)
        self._delay_button.props.label = _('Capture delay')
        self._delay_button.connect('clicked',
                self.__change_capture_delay_cb)
        self._live_toolbar_container.add(self._delay_button)
        self._delay_button.show()

        self._zoom_button = ToolButton('zoom_%d' % self._zoom)
        self._zoom_button.props.label = _('Image Zoom')
        self._zoom_button.connect('clicked',
                self.__change_image_zoom_cb)
        self._live_toolbar_container.add(self._zoom_button)
        self._zoom_button.show()

        #if self._check_available_control(v4l2.V4L2_CID_EXPOSURE):
        #    self._bracketing_button = ToolButton('bracketing_%s' % self._bracketing)
        #    self._bracketing_button.props.label = _('bracketing mode')
        #    self._bracketing_button.connect('clicked',
        #            self.__change_capture_bracketing_cb)
        #    self._live_toolbar_container.add(self._bracketing_button)
        #    self._bracketing_button.show()

        separator = gtk.SeparatorToolItem()
        separator.props.draw = True
        separator.set_expand(False)
        self._live_toolbar_container.add(separator)
        separator.show()

        # Camera control settings follow

        if self._check_available_control(v4l2.V4L2_CID_EXPOSURE):
            self._exposure_button = ToolButton('exposure')
            self._exposure_button.set_palette(ScalePalette('Exposure',\
                    v4l2.V4L2_CID_EXPOSURE))
            self._exposure_button.connect('clicked',
                    self.__button_clicked_cb)
            self._live_toolbar_container.add(self._exposure_button)
            self._exposure_button.show()

        if self._check_available_control(v4l2.V4L2_CID_GAIN):
            self._gain_button = ToolButton('gain')
            self._gain_button.set_palette(ScalePalette('Gain',\
                    v4l2.V4L2_CID_GAIN,
                    self._check_available_control(v4l2.V4L2_CID_AUTOGAIN)))
            self._gain_button.connect('clicked',
                    self.__button_clicked_cb)
            advanced_toolbar.insert(self._gain_button, -1)
            self._gain_button.show()

        if self._check_available_control(v4l2.V4L2_CID_BRIGHTNESS):
            self._brightness_button = ToolButton('brightness')
            self._brightness_button.set_palette(ScalePalette('Brightness',\
                    v4l2.V4L2_CID_BRIGHTNESS,
                    self._check_available_control(
                        v4l2.V4L2_CID_AUTOBRIGHTNESS)))
            self._brightness_button.connect('clicked',
                    self.__button_clicked_cb)
            self._live_toolbar_container.add(self._brightness_button)
            self._brightness_button.show()

        if self._check_available_control(v4l2.V4L2_CID_CONTRAST):
            self._contrast_button = ToolButton('contrast')
            self._contrast_button.set_palette(ScalePalette('Contrast',\
                    v4l2.V4L2_CID_CONTRAST))
            self._contrast_button.connect('clicked',
                    self.__button_clicked_cb)
            self._live_toolbar_container.add(self._contrast_button)
            self._contrast_button.show()

        if self._check_available_control(v4l2.V4L2_CID_SATURATION):
            self._saturation_button = ToolButton('saturation')
            self._saturation_button.set_palette(ScalePalette('Saturation',\
                    v4l2.V4L2_CID_SATURATION))
            self._saturation_button.connect('clicked',
                    self.__button_clicked_cb)
            advanced_toolbar.insert(self._saturation_button, -1)
            self._saturation_button.show()

        if self._check_available_control(
                v4l2.V4L2_CID_WHITE_BALANCE_TEMPERATURE):
            self._white_balance_button = ToolButton('white_balance')
            self._white_balance_button.set_palette(ScalePalette('White'
                    ' balance', v4l2.V4L2_CID_WHITE_BALANCE_TEMPERATURE,
                    self._check_available_control(
                        v4l2.V4L2_CID_AUTO_WHITE_BALANCE)))
            self._white_balance_button.connect('clicked',
                    self.__button_clicked_cb)
            advanced_toolbar.insert(self._white_balance_button, -1)
            self._white_balance_button.show()

        if self._check_available_control(v4l2.V4L2_CID_HUE):
            self._color_tone_button = ToolButton('color_tone')
            self._color_tone_button.set_palette(ScalePalette('Color'
                    ' tone', v4l2.V4L2_CID_HUE,
                    self._check_available_control(
                        v4l2.V4L2_CID_HUE_AUTO)))
            self._color_tone_button.connect('clicked',
                    self.__button_clicked_cb)
            advanced_toolbar.insert(self._color_tone_button, -1)
            self._color_tone_button.show()

        #if self._check_available_control(v4l2.V4L2_CID_NIGHT_MODE):
        #    self._night_mode_button = ToolButton('night_mode')
        #    self._night_mode_button.set_palette(ScalePalette('Night mode',\
        #            v4l2.V4L2_CID_NIGHT_MODE))
        #    self._night_mode_button.connect('clicked',
        #            self.__button_clicked_cb)
        #    self._live_toolbar_container.add(self._night_mode_button)
        #    self._night_mode_button.show()

        self._previous_image = ToolButton('go-previous-paired')
        self._previous_image.label = _('Previous image')
        self._previous_image.connect('clicked',
                self.__previous_image_clicked_cb)
        self._preview_toolbar_container.add(self._previous_image)
        self._previous_image.show()

        self._next_image = ToolButton('go-next-paired')
        self._next_image.label = _('Next image')
        self._next_image.connect('clicked',
                self.__next_image_clicked_cb)
        self._preview_toolbar_container.add(self._next_image)
        self._next_image.show()

        self._image_name_entry = gtk.Entry()
        self._image_name_entry.set_text('')
        self._image_name_entry.set_size_request(400, -1)
        self._image_name_entry.connect('activate',
                self.__image_name_entry_activated_cb)
        self._preview_toolbar_container.add(self._image_name_entry)
        self._image_name_entry.show()

        self._save_to_journal = ToolButton('save_to_journal')
        self._save_to_journal.label = _('Save to journal')
        self._save_to_journal.connect('clicked',
                self.__save_to_journal_clicked_cb)
        self._preview_toolbar_container.add(self._save_to_journal)
        self._save_to_journal.show()

        self._trash = ToolButton('trash')
        self._trash.label = _('Delete')
        self._trash.connect('clicked',
                self.__trash_clicked_cb)
        self._preview_toolbar_container.add(self._trash)
        self._trash.show()

        separator = gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        self._controls_toolbar.insert(separator, -1)
        separator.show()

        self._mode_button = ToolButton('%s_mode' % self._mode)
        self._mode_button.props.label = _('Mode')
        self._mode_button.connect('clicked',
                self.__switch_modes_cb)
        self._controls_toolbar.insert(self._mode_button, -1)
        self._mode_button.show()

        if not OLD_TOOLBAR:
            separator = gtk.SeparatorToolItem()
            separator.props.draw = True
            separator.set_expand(False)
            self._controls_toolbar.insert(separator, -1)
            separator.show()

            activity_stop = StopButton(self)
            toolbar_box.toolbar.insert(activity_stop, -1)
            activity_stop.show()

        self._preview_toolitem.add(self._preview_toolbar_container)
        self._live_toolitem.add(self._live_toolbar_container)
        self._preview_toolbar_container.show()
        self._live_toolbar_container.show()

        if self._mode == 'preview':
            self._controls_toolbar.insert(self._preview_toolitem, 1)
            self._preview_toolitem.show()
        else:
            self._controls_toolbar.insert(self._live_toolitem, 1)
            self._live_toolitem.show()
            self._mode = 'live'

        self._controls_toolbar.show()
        activity_toolbar.show()

        self._main_view = gtk.HBox()
        self._movie_window = gtk.DrawingArea()
        self._movie_window.connect('realize',
                self.__movie_window_realize_cb)
        self._movie_window.unset_flags(gtk.DOUBLE_BUFFERED)
        self._movie_window.set_flags(gtk.APP_PAINTABLE)
        self._main_view.add(self._movie_window)

        self._preview_frame = gtk.AspectFrame(None, 0.5, 0.5, 1, True)
        self._preview_window = gtk.Image()
        self._preview_frame.add(self._preview_window)
        self._preview_window.connect('size_allocate',
                self.__preview_window_size_allocate_cb)

        self.xoscope = gst.Pipeline('xoscope_pipe')
        camsrc = gst.element_factory_make('v4l2src', 'camsrc')

        caps = gst.Caps('video/x-raw-yuv')

        filt = gst.element_factory_make('capsfilter', 'filter')
        filt.set_property('caps', caps)
        ffmpegcolorspace = gst.element_factory_make('ffmpegcolorspace',
                'ffmpegcolorspace')
        self._disp_sink = gst.element_factory_make('xvimagesink', 'disp_sink')

        # http://thread.gmane.org/gmane.comp.video.gstreamer.devel/29644
        self._disp_sink.set_property('sync', False)

        self.image_sink = gst.element_factory_make('fakesink',
                'image_sink')
        self.image_sink.set_property('silent', True)

        tee = gst.element_factory_make('tee', 'tee')
        queue = gst.element_factory_make('queue', 'dispqueue')
        queue.set_property('leaky', True)
        queue.set_property('max-size-buffers', 20)

        queue2 = gst.element_factory_make('queue', 'imagequeue')
        queue2.set_property('leaky', True)
        queue2.set_property('max-size-buffers', 20)

        self._zoom_element = gst.element_factory_make('videobox', 'zoombox')

        jpeg = gst.element_factory_make('jpegenc', 'pbjpeg')
        jpeg.set_property('quality', 100)

        self.xoscope.add(camsrc, filt, ffmpegcolorspace,\
                self._zoom_element, self._disp_sink, tee, queue, queue2,\
                self.image_sink, jpeg)
        gst.element_link_many(camsrc, filt, self._zoom_element,\
                ffmpegcolorspace, tee, queue, self._disp_sink)
        gst.element_link_many(tee, queue2, jpeg, self.image_sink)

        bus = self.xoscope.get_bus()
        bus.add_signal_watch()
        bus.enable_sync_message_emission()
        bus.connect('message', self.__on_message_cb)
        bus.connect('sync-message::element', self.__on_sync_message_cb)

        self._main_view.show()
        self._movie_window.show()
        self.set_canvas(self._main_view)

        # If we start playing without a delay, the live view window
        # doesn't get attached to the main canvas properly (This is
        # a problem on slow computers like xo1).
        gobject.timeout_add(2000, self.__start_live_view)

    def __preview_window_size_allocate_cb(self, gobject, allocation):
        # Make sure we don't get stuck in an infinite loop
        if self._needs_resize:
            pixbuf = self._preview_window.get_pixbuf()
            new_pixbuf = pixbuf.scale_simple(allocation.width,\
                    allocation.height, gtk.gdk.INTERP_BILINEAR)
            self._preview_window.set_from_pixbuf(new_pixbuf)
            self._preview_window.show()
            self._needs_resize = False
        else:
            return

    def read_file(self, path):
        logging.debug('read_file %s' % path)
        try:
            dom = minidom.parse(path)
        except Exception, e:
            logging.error('read_file: %s' % e)
            return

        logging.debug('read file, now filling hash')
        self._fill_info_hash(dom)
        self._update_zoom_element_and_button()
        self._delay_button.set_icon('delay_%d' % self._delay)

    def write_file(self, path):
        logging.debug('write_file %s' % path)
        try:
            doc = minidom.Document()
            head = doc.createElement('XoScope-information-table')
            doc.appendChild(head)

            num_pics = doc.createElement('num-pics')
            head.appendChild(num_pics)
            num_pics.setAttribute('number', str(self._num_pics))

            pic_index = doc.createElement('pic-index')
            head.appendChild(pic_index)
            pic_index.setAttribute('number', str(self._pic_index))

            live_zoom = doc.createElement('live-zoom')
            head.appendChild(live_zoom)
            live_zoom.setAttribute('number', str(self._zoom))

            live_delay = doc.createElement('live-delay')
            head.appendChild(live_delay)
            live_delay.setAttribute('number', str(self._delay))

            for image in self._images:
                image_element = doc.createElement('image')
                head.appendChild(image_element)
                image_element.setAttribute('name', image['name'])
                image_element.setAttribute('title', image['title'])

            logging.debug(doc.toprettyxml(indent = '   '))

        except Exception, e:
            logging.error('write_file: %s' % e)
            return

        f = open(path, 'w')
        doc.writexml(f, indent = '    ')

    def _fill_info_hash(self, doc):
        self._num_pics =\
                int(doc.documentElement.getElementsByTagName('num-pics')\
                .item(0).getAttribute('number'))
        self._pic_index =\
                int(doc.documentElement.getElementsByTagName('pic-index')\
                .item(0).getAttribute('number'))
        self._zoom =\
                int(doc.documentElement.getElementsByTagName('live-zoom')\
                .item(0).getAttribute('number'))
        self._delay =\
                int(doc.documentElement.getElementsByTagName('live-delay')\
                .item(0).getAttribute('number'))
        image_elements =\
                doc.documentElement.getElementsByTagName('image')

        logging.debug('num_pics %d' % self._num_pics)
        logging.debug('pic_index %d' % self._pic_index)

        for image_element in image_elements:
            image_hash = {}
            image_hash['name'] = image_element.getAttribute('name')
            image_hash['title'] = image_element.getAttribute('title')
            self._images.append(image_hash)
            logging.debug(self._images)

    def __save_to_journal_clicked_cb(self, gobject):
        filename = self._images[self._pic_index]['name']
        imgpath = os.path.join(self._instance_directory, filename)

        journal_entry = datastore.create()
        journal_entry.metadata['title'] =\
                self._images[self._pic_index]['title']
        journal_entry.metadata['mime_type'] = 'image/jpeg'
        journal_entry.metadata['tags'] = 'XoScope'
        journal_entry.set_file_path(imgpath)
        datastore.write(journal_entry)
        journal_entry.destroy()

    def __trash_clicked_cb(self, gobject):
        self._needs_resize = True
        filename_current = self._images[self._pic_index]['name']
        imgpath_current = os.path.join(self._instance_directory,\
                filename_current)

        if self._num_pics == 0:
            return
        else:
            if self._num_pics <= 2:
                logging.debug('num_pics: %d' % self._num_pics)
                logging.debug('pic_index: %d' % self._pic_index)
                self._next_image.set_sensitive(False)
                self._previous_image.set_sensitive(False)
                self._images.pop(self._pic_index)
                self._pic_index = 0
                logging.debug('num_pics: %d' % self._num_pics)
                logging.debug('pic_index: %d' % self._pic_index)

                if self._num_pics == 1:
                    self._image_name_entry.set_text('')
                    self._image_name_entry.set_editable(False)
                    self._save_to_journal.set_sensitive(False)
                    self._trash.set_sensitive(False)
                    self._preview_window.clear()
                else:
                    self._preview_window.set_from_file(\
                        os.path.join(self._instance_directory,
                            self._images[self._pic_index]['name']))

                self._num_pics = self._num_pics - 1
                os.remove(imgpath_current)

            else:
                self._images.pop(self._pic_index)
                self._num_pics = self._num_pics - 1
                self.__next_image_clicked_cb(gobject)
                os.remove(imgpath_current)

    def __fakesink_probe_cb(self, gobject, buffer, user_data=None):
        self._fakesink_probe.remove_buffer_probe(self._fakesink_probe_handle)

        pic = gtk.gdk.pixbuf_loader_new_with_mime_type('image/jpeg')
        pic.write( buffer )
        pic.close()

        filename = 'image_' + str(int(time.time())) + '.jpg'
        title = (self.get_metadata())['title']
        imgpath = os.path.join(self.get_activity_root(), 'instance', filename)
        pixbuf = pic.get_pixbuf()
        pixbuf.save( imgpath, 'jpeg', {'quality':'100'})

        self._num_pics = self._num_pics + 1

        self._images.append({'name':filename,'title':title})

        del self._fakesink_probe

        return True

    # Small but significant piece of code
    # * http://gstreamer-devel.966125.n4.nabble.com/unreliable-
    #    xvimagesink-rendering-to-GTK-elements-td3225872.html
    # * http://gstreamer.freedesktop.org/data/doc/gstreamer/head
    #    /gst-plugins-base-libs/html/gst-plugins-base-libs-gstxo
    #    verlay.html#gst-plugins-base-libs-gstxoverlay.description
    def __movie_window_realize_cb(self, gobject):
        self._movie_window_xid = self._movie_window.window.xid

    def __start_live_view(self):
        self.xoscope.set_state(gst.STATE_PLAYING)
        return False

    def __image_name_entry_activated_cb(self, gobject):
        logging.debug(self._image_name_entry.get_text())
        self._images[self._pic_index]['title'] =\
                self._image_name_entry.get_text()

    def __next_image_clicked_cb(self, gobject):
        self._needs_resize = True
        if self._num_pics <= 1:
            return
        else:
            if self._pic_index < (self._num_pics - 1):
                self._pic_index = self._pic_index + 1
            elif self._pic_index == (self._num_pics - 1):
                self._pic_index = 0
            else:
                logging.error('Index of displayed picture exceeded'
                        'maximum number of images to display')
            self._preview_window.set_from_file(\
                    os.path.join(self._instance_directory,
                        self._images[self._pic_index]['name']))
            self._image_name_entry.set_text(\
                    self._images[self._pic_index]['title'])
            self._preview_frame.show_all()

    def __previous_image_clicked_cb(self, gobject):
        self._needs_resize = True
        if self._num_pics <= 1:
            return
        else:
            if self._pic_index > 0:
                self._pic_index = self._pic_index - 1
            elif self._pic_index == 0:
                self._pic_index = (self._num_pics - 1)
            else:
                logging.error('Index of displayed picture exceeded'
                        'maximum number of images to display')
            self._preview_window.set_from_file(\
                    os.path.join(self._instance_directory,
                        self._images[self._pic_index]['name']))
            self._image_name_entry.set_text(\
                    self._images[self._pic_index]['title'])
            self._preview_frame.show_all()

    def __switch_modes_cb(self, gobject):
        if self._mode == 'live':
            self._needs_resize = True
            self._mode = 'preview'
            self._controls_toolbar.remove(self._live_toolitem)
            self._controls_toolbar.insert(self._preview_toolitem, 1)
            self._preview_toolitem.show()

            if self._num_pics > 0:
                self._image_name_entry.set_editable(True)
                self._save_to_journal.set_sensitive(True)
                self._trash.set_sensitive(True)
                self._preview_window.set_from_file(\
                    os.path.join(self._instance_directory,
                        self._images[self._pic_index]['name']))
                self._image_name_entry.set_text(\
                        self._images[self._pic_index]['title'])
                if self._num_pics == 1:
                    self._next_image.set_sensitive(False)
                    self._previous_image.set_sensitive(False)
                else:
                    self._next_image.set_sensitive(True)
                    self._previous_image.set_sensitive(True)
            else:
                self._image_name_entry.set_editable(False)
                self._next_image.set_sensitive(False)
                self._previous_image.set_sensitive(False)
                self._save_to_journal.set_sensitive(False)
                self._trash.set_sensitive(False)

            self.xoscope.set_state(gst.STATE_NULL)
            self._main_view.remove(self._movie_window)
            self._main_view.add(self._preview_frame)
            self._preview_frame.show_all()
            self._main_view.show()
            self.set_canvas(self._main_view)

        elif self._mode == 'preview':
            self._mode = 'live'
            self._controls_toolbar.remove(self._preview_toolitem)
            self._controls_toolbar.insert(self._live_toolitem, 1)
            self._live_toolitem.show_all()

            self._main_view.remove(self._preview_frame)
            self._main_view.add(self._movie_window)
            self.xoscope.set_state(gst.STATE_PLAYING)
            self._movie_window.show()
            self._main_view.show()
            self.set_canvas(self._main_view)

        else:
            logging.error('Mode variable got screwed up!!!')
            self._mode = 'live'

        self._mode_button.set_icon('%s_mode' % self._mode)
        self._mode_button.show()

    def _update_zoom_element_and_button(self):
        # Works for xo only
        dim_x = 640
        dim_y = 480

        crop_x = int( 0.5 * dim_x * (1 - (1 / float(self._zoom))))
        crop_y = int( 0.5 * dim_y * (1 - (1 / float(self._zoom))))

        self.xoscope.set_state(gst.STATE_NULL)
        self._zoom_element.set_property('left', crop_x)
        self._zoom_element.set_property('right', crop_x)
        self._zoom_element.set_property('top', crop_y)
        self._zoom_element.set_property('bottom', crop_y)
        self.xoscope.set_state(gst.STATE_PLAYING)

        self._zoom_button.set_icon('zoom_%d' % self._zoom)

    def __change_image_zoom_cb(self, gobject):
        if self._zoom == 1:
            self._zoom = 2
        elif self._zoom == 2:
            self._zoom = 3
        elif self._zoom == 3:
            self._zoom = 4
        elif self._zoom == 4:
            self._zoom = 1
        else: #exception
            self._zoom = 1
            logging.warning('zoom is not one of 1, 2, 3 or 4')

        self._update_zoom_element_and_button()

    def __change_capture_bracketing_cb(self, gobject):
        if self._bracketing == '0':
            self._bracketing = '2'
        elif self._bracketing == '2':
            self._bracketing = '4'
        elif self._bracketing == '4':
            self._bracketing = '0'
        else: #exception
            self._bracketing = '0'
            logging.warning('bracketing is not one of 0, 2 or 4')

        self._bracketing_button.set_icon('bracketing_%s' % self._bracketing)

    def __change_capture_delay_cb(self, gobject):
        if self._delay == 0:
            self._delay = 2
        elif self._delay == 2:
            self._delay = 5
        elif self._delay == 5:
            self._delay = 0
        else: #exception
            self._delay = 0
            logging.warning('Delay is not one of 0, 2 or 5 seconds')

        self._delay_button.set_icon('delay_%d' % self._delay)

    def __button_clicked_cb(self, gobject):
        gobject.palette.popup(immediate=True, state=1)

    def __capture_image_cb(self, w):

        if int(self._bracketing) > 0:
            v4l2_control = v4l2.V4L2_CID_EXPOSURE
            if self._check_available_control(v4l2_control):
                self._control = v4l2.v4l2_control(v4l2_control)
                ioctl(VD, v4l2.VIDIOC_G_CTRL, self._control)
                self._exposure_value = self._control.value
                gobject.timeout_add((1000 * int(self._delay)),
                        self.__delayed_capture_image_cb, w)
                # two more pictures
                self._bracketing_count = 2
        else:
            gobject.timeout_add((1000 * int(self._delay)),
                    self.__delayed_capture_image_cb, w)

    def __delayed_capture_image_cb(self, w):
        logging.debug('capturing_image_cb')
        #os.system('aplay %s' % os.path.join(activity.get_bundle_path(),
        #            'sounds/shutter.wav'))

        self._fakesink_probe = self.image_sink.get_pad('sink')
        self._fakesink_probe_handle = \
                self._fakesink_probe.add_buffer_probe(self.__fakesink_probe_cb,\
                None)

        return False

    def _check_available_control(self, v4l2_control):
        control = v4l2.v4l2_control(v4l2_control)
        try:
            ioctl(VD, v4l2.VIDIOC_QUERYCTRL, control)
        except IOError:
            logging.exception('error setting control')
            return False
        else:
            return v4l2_control

    def __on_message_cb(self, bus, message):
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.xoscope.set_state(gst.STATE_NULL)
            self.button.set_label('Start')
        elif t == gst.MESSAGE_ERROR:
            err, debug = message.parse_error()
            logging.error('Error: %s' % err, debug)
            self.xoscope.set_state(gst.STATE_NULL)
            self.button.set_label('Start')

    def __on_sync_message_cb(self, bus, message):
        if message.structure is None:
            return
        message_name = message.structure.get_name()
        if message_name == 'prepare-xwindow-id':
            if self._movie_window_xid != 0:
                # Assign the viewport
                imagesink = message.src
                imagesink.set_property('force-aspect-ratio', True)
                imagesink.set_xwindow_id(self._movie_window_xid)
            else:
                logging.warn('Should have obtained the movie_window_xid'
                'by now')

