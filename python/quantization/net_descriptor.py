'''
This script reads out a given prototxt file to extract the network layout
Based on this network layout we create a new prototxt for either training or testing
Script cleaned BUT NOT COMMENTED

Author: Moritz Milde
Date: 02.11.2016
E-Mail: mmilde@ini.uzh.ch
'''

import numpy as np
import caffe
import collections as c
from caffe.proto import caffe_pb2
from google.protobuf import text_format


class net_prototxt():
    def __init__(self):
        self.model_dir = '/home/moritz/Repositories/caffe_lp/examples/low_precision/imagenet/models/'
        self.weight_dir = '/media/moritz/Data/ILSVRC/pre_trained/'
        self.layer_dir = '/home/moritz/Repositories/caffe_lp/examples/create_prototxt/layers/'
        self.save_dir = '/home/moritz/Repositories/caffe_lp/examples/low_precision/imagenet/models/'

    def get_model(self, prototxt, caffemodel):
        model = caffe.Net(prototxt, caffemodel, caffe.TEST)
        model_protobuf = caffe.proto.caffe_pb2.NetParameter()
        text_format.Merge(open(prototxt).read(), model_protobuf)
        return {'model': (model, model_protobuf), 'val_fn': model.forward_all}

    def extract(self, net_name, mode='deploy',
                model_dir=None, weight_dir=None, model=None, stride_conv=1, pad=0, debug=False):
        if model_dir is not None:
            self.model_dir = model_dir
        if weight_dir is not None:
            self.weight_dir = weight_dir

        prototxt = self.model_dir + net_name + '_deploy.prototxt'
        # check if h5 or not??
        net_weights = self.weight_dir + net_name + '.caffemodel'
        if model is None:
            model = net_prototxt.get_model(self, prototxt, net_weights)
        else:
            model_protobuf = caffe.proto.caffe_pb2.NetParameter()
            text_format.Merge(open(prototxt).read(), model_protobuf)
            model = {'model': (model, model_protobuf)}

        caffe_model = model['model'][0]
        caffe_layers = model['model'][1].layer
        self.net_descriptor = []
        for (layer_num, layer) in enumerate(caffe_layers):
            if debug:
                if layer.type == 'Convolution':
                    p = layer.convolution_param
                    print 'Type: {}'.format(layer.type)
                    print 'Pad: {}'.format(p.pad._values[0])
                    print 'Stride {}'.format(p.stride._values[0])
                    print 'Kernel size: {}'.format(p.kernel_size._values[0])
                    print 'Output Channels {}'.format(p.num_output)
                    print '----------------------'
                if layer.type == 'Pooling':
                    p = layer.pooling_param
                    print 'Type: {}'.format(layer.type)
                    print 'Kernel size: {}'.format(p.kernel_size)
                    print 'Stride: {}'.format(p.stride)
                    print '----------------------'
                if layer.type == 'Dropout':
                    p = layer.dropout_param
                    print 'Type: {}'.format(layer.type)
                    print 'Dropout ratio: {}'.format(p.dropout_ratio)
                    print '----------------------'

            if 'Conv' in layer.type or 'LPConv' in layer.type:
                p = layer.convolution_param
                layer_output = str(p.num_output)
                layer_type = 'C'
                if not p.stride:
                    layer_stride = 'S' + str(stride_conv)
                else:
                    layer_stride = 'S' + str(p.stride._values[0])
                if not p.pad:
                    layer_pad = 'p' + str(pad)
                else:
                    layer_pad = 'p' + str(p.pad._values[0])

                layer_kernel = str(p.kernel_size._values[0])
                layer_descriptor = layer_output + layer_type + \
                    layer_kernel + layer_stride + layer_pad

                # 2P2 POOLING
            elif layer.type == 'Pooling':
                p = layer.pooling_param
                layer_type = 'P'
                layer_kernel = str(p.kernel_size)
                layer_stride = str(p.stride)
                layer_descriptor = layer_kernel + layer_type + layer_stride

            elif 'Drop' in layer.type:
                p = layer.dropout_param
                layer_type = 'D'
                layer_ratio = str(int(p.dropout_ratio * 10))
                layer_descriptor = layer_type + layer_ratio

            elif 'Inner' in layer.type or 'LPInner' in layer.type:
                p = layer.inner_product_param
                layer_type = 'F'
                layer_output = str(p.num_output)
                layer_descriptor = layer_output + layer_type

            elif layer.type == 'ReLU':
                layer_type = 'ReLU'
                layer_descriptor = layer_type

            elif layer.type == 'Accuracy':
                p = layer.accuracy_param
                layer_type = 'Accuracy'
                if p.top_k == 5:
                    continue
                layer_descriptor = layer_type

            else:
                layer_descriptor = ''
                continue
            try:
                self.net_descriptor.append(layer_descriptor)
            except UnboundLocalError:
                pass
            try:
                if layer_type == 'C':
                    self.net_descriptor.append('A')
                elif layer_type == 'F' and p.num_output > 1001:
                    self.net_descriptor.append('A')
            except UnboundLocalError:
                pass
            if layer_type == 'Accuracy':
                if mode == 'train':
                    self.net_descriptor.append('loss')
        return self.net_descriptor

    def create(self, net_descriptor, bit_distribution_weights, bit_distribution_act, net_name='VGG16',
               init_method='xavier', lp=True, deploy=False, visualize=False, round_bias='false',
               layer_dir=None, model_dir=None):
        # This function should either call or execute the create_prototxt
        # script
        if layer_dir is not None:
            self.layer_dir = layer_dir
        if model_dir is not None:
            self.model_dir = model_dir
        self.net_descriptor = net_descriptor

        if not lp:
            for i, j in enumerate(self.net_descriptor):
                if j == 'A':
                    self.net_descriptor.pop(i)

        layer = c.namedtuple('layer', ['name', 'name_old' 'type', 'bottom', 'top', 'counter', 'bd', 'ad', 'kernel', 'group',
                                       'stride', 'pad', 'bias', 'output', 'pool_size', 'pool_type', 'round_bias', 'dropout_rate'])
        # Perform layerwise assignment

        layer.round_bias = round_bias
        layer.counter = 1
        layer.name_old = 'data'

        if lp:
            if deploy:
                filename = '%s_%i_bit_deploy.prototxt' % (
                    net_name, bit_distribution_weights[0, 0] + bit_distribution_weights[1, 0])
                filename = 'LP_' + filename
                if visualize:
                    filename = '%s_%i_bit_vis.prototxt' % (
                        net_name, bit_distribution_weights[0, 0] + bit_distribution_weights[1, 0])
                    filename = 'LP_' + filename
            else:
                filename = '%s_%i_bit_train.prototxt' % (
                    net_name, bit_distribution_weights[0, 0] + bit_distribution_weights[1, 0])
                filename = 'LP_' + filename
        else:
            if deploy:
                filename = '%s_deploy.prototxt' % (net_name)
                if visualize:
                    filename = '%s_vis.prototxt' % (net_name)
            else:
                filename = '%s_train.prototxt' % (net_name)

        print 'Generating ' + filename
        weight_counter = 0
        act_counter = 0
        for cLayer in self.net_descriptor:
            if np.size(bit_distribution_weights, 1) > 1:
                if cLayer == 'A':
                    # Set bit precision of Conv and ReLUs
                    layer.bd = bit_distribution_act[0, act_counter]
                    layer.ad = bit_distribution_act[1, act_counter]
                    act_counter += 1
                elif 'C' in cLayer or 'F' in cLayer:
                    # Set bit precision of Conv and ReLUs
                    layer.bd = bit_distribution_weights[0, weight_counter]
                    layer.ad = bit_distribution_weights[1, weight_counter]
                    weight_counter += 1
            else:
                layer.bd = bit_distribution_weights[0, 0]
                layer.ad = bit_distribution_weights[1, 0]

            if layer.counter < 2:
                layer_base = open(self.layer_dir + 'layer_base.prototxt', 'wr')
            else:
                layer_base = open(self.layer_dir + 'layer_base.prototxt', 'a')
            if 'C' in cLayer:
                # print 'Convolution'
                layer.name = 'conv'
                layer.type = 'Convolution'
                layer.output = cLayer.partition("C")[0]
                layer.kernel = cLayer.partition("C")[2].partition("S")[0]
                layer.stride = cLayer.partition("S")[2][0]
                if 'p' in cLayer:
                    layer.pad = cLayer.partition("S")[2].partition("p")[2]
                else:
                    layer.pad = 0
                if deploy:
                    if lp:
                        layer.name += '_lp'
                        layer.type = 'LPConvolution'
                        lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                          '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                            layer.name, layer.counter),
                            '  param {\n', '    lr_mult: 1\n', '   }\n',
                            '  param {\n', '    lr_mult: 2\n', '   }\n',
                            '  lpfp_param {\n', '    bd: %i\n' % (layer.bd), '    ad: %i\n' % (
                                              layer.ad), '    round_bias: %s\n' % (layer.round_bias), '  }\n',
                            '  convolution_param {\n', '    num_output: %s\n' % (layer.output), '    stride: %s\n' % (
                                              layer.stride), '    kernel_size: %s\n' % (layer.kernel), '    pad: %s\n' % (layer.pad),
                            '  }\n',
                            '}\n']
                    else:
                        lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                          '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                            layer.name, layer.counter),
                            '  param {\n', '    lr_mult: 1\n', '   }\n',
                            '  param {\n', '    lr_mult: 2\n', '   }\n',
                            '  convolution_param {\n', '    num_output: %s\n' % (
                                              layer.output), '    stride: %s\n' % (layer.stride),
                            '    kernel_size: %s\n' % (
                                              layer.kernel), '    pad: %s\n' % (layer.pad),
                            '  }\n',
                            '}\n']
                else:
                    if init_method == 'gaussian':
                        if lp:
                            layer.name += '_lp'
                            layer.type = 'LPConvolution'
                            lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                              '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                                layer.name, layer.counter),
                                '  param {\n', '    lr_mult: 1\n', '    decay_mult: 1\n', '   }\n',
                                '  param {\n', '    lr_mult: 2\n', '    decay_mult: 0\n', '   }\n',
                                '  lpfp_param {\n', '    bd: %i\n' % (layer.bd), '    ad: %i\n' % (
                                                  layer.ad), '    round_bias: %s\n' % (layer.round_bias), '  }\n',
                                '  convolution_param {\n', '    num_output: %s\n' % (layer.output), '    stride: %s\n' % (
                                                  layer.stride), '    kernel_size: %s\n' % (layer.kernel),
                                '    weight_filler {\n', '      type: "gaussian"\n', '      std: 0.01\n', '   }\n',
                                '    bias_filler {\n', '      type: "constant"\n', '      value: 0.0\n', '   }\n',
                                '  }\n',
                                '}\n']
                        else:
                            lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                              '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                                layer.name, layer.counter),
                                '  param {\n', '    lr_mult: 1\n', '    decay_mult: 1\n', '   }\n',
                                '  param {\n', '    lr_mult: 2\n', '    decay_mult: 0\n', '   }\n',
                                '  convolution_param {\n', '    num_output: %s\n' % (
                                                  layer.output), '    stride: %s\n' % (layer.stride),
                                '    kernel_size: %s\n' % (
                                                  layer.kernel), '    pad: %s\n' % (layer.pad),
                                '    weight_filler {\n', '      type: "gaussian"\n', '      std: 0.01\n', '   }\n',
                                '    bias_filler {\n', '      type: "constant"\n', '      value: 0.0\n', '   }\n',
                                '  }\n',
                                '}\n']
                    if init_method == 'xavier':
                        if lp:
                            layer.name += '_lp'
                            layer.type = 'LPConvolution'
                            lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                              '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                                layer.name, layer.counter),
                                '  param {\n', '    lr_mult: 1\n', '    decay_mult: 1\n', '   }\n',
                                '  param {\n', '    lr_mult: 2\n', '    decay_mult: 0\n', '   }\n',
                                '  lpfp_param {\n', '    bd: %i\n' % (layer.bd), '    ad: %i\n' % (
                                                  layer.ad), '    round_bias: %s\n' % (layer.round_bias), '  }\n',
                                '  convolution_param {\n', '    num_output: %s\n' % (layer.output), '    stride: %s\n' % (
                                                  layer.stride), '    kernel_size: %s\n' % (layer.kernel), '    pad: %s\n' % (layer.pad),
                                '    weight_filler {\n', '      type: "xavier"\n', '   }\n',
                                '    bias_filler {\n', '      type: "constant"\n', '      value: 0.0\n', '   }\n',
                                '  }\n',
                                '}\n']
                        else:
                            lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                              '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                                layer.name, layer.counter),
                                '  param {\n', '    lr_mult: 1\n', '    decay_mult: 1\n', '   }\n',
                                '  param {\n', '    lr_mult: 2\n', '    decay_mult: 0\n', '   }\n',
                                '  convolution_param {\n', '    num_output: %s\n' % (layer.output), '    stride: %s\n' % (
                                                  layer.stride), '    kernel_size: %s\n' % (layer.kernel), '    pad: %s\n' % (layer.pad),
                                '    weight_filler {\n', '      type: "xavier"\n', '   }\n',
                                '    bias_filler {\n', '      type: "constant"\n', '      value: 0.0\n', '   }\n',
                                '  }\n',
                                '}\n']

                layer_base.writelines(lines_to_write)

            if cLayer == 'A':
                # print 'Activation'
                layer.name = 'act'
                layer.type = 'Act'
                if lp:
                    layer.name += '_lp'
                    layer.type = 'LPAct'
                    lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                      '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                        layer.name, layer.counter),
                        '  lpfp_param {\n', '    bd: %i\n' % (layer.bd), '    ad: %i\n' % (
                        layer.ad), '    round_bias: %s' % (layer.round_bias), '  }\n',
                        '}\n']

                layer_base.writelines(lines_to_write)

            if cLayer == 'ReLU':
                # print 'ReLU'
                if lp:
                    layer.name = 'relu'
                    layer.type = 'ReLU'
                    lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                      '  bottom: "%s"\n' % (
                        layer.name_old), '  top: "%s"\n' % (layer.name_old),
                        '}\n']
                else:
                    layer.name = 'relu'
                    layer.type = 'ReLU'
                    lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                      '  bottom: "%s"\n' % (
                        layer.name_old), '  top: "%s"\n' % (layer.name_old),
                        '}\n']
                layer_base.writelines(lines_to_write)
            if 'P' in cLayer:
                # print 'Pooling'
                layer.name = 'pool'
                layer.type = 'Pooling'
                layer.pool_type = 'MAX'
                layer.pool_size = cLayer.partition("P")[0]
                layer.stride = cLayer.partition("P")[2]
                lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                  '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                    layer.name, layer.counter),
                    '  pooling_param {\n', '    pool: %s\n' % (layer.pool_type), '    kernel_size: %s\n' % (
                    layer.pool_size), '    stride: %s\n' % (layer.stride),
                    '  }\n',
                    '}\n']

                layer_base.writelines(lines_to_write)
            if cLayer == 'RoI':
                layer.name = 'roi'
                layer.type = 'ROIPooling'
                roi_width = 7
                roi_height = 7
                lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                  '  bottom: "%s"\n' % (layer.name_old), '  bottom: "rois"\n', '  top: "%s_%i"\n' % (
                    layer.name, layer.counter),
                    '  roi_pooling_param {\n', '    pooled_w: %i\n' % (
                    roi_width), '    pooled_h: %i\n' % (roi_height),
                    '    spatial_scale: 0.625\n',
                    '  }\n',
                    '}\n']
                layer_base.writelines(lines_to_write)
            if 'F' in cLayer:
                # print 'Fully Connected'
                layer.name = 'fc'
                layer.type = 'InnerProduct'
                layer.output = cLayer.partition("F")[0]
                if deploy:
                    if lp:
                        layer.name += '_lp'
                        layer.type = 'LPInnerProduct'
                        lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                          '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                            layer.name, layer.counter),
                            '  param {\n', '    lr_mult: 1\n', '   }\n',
                            '  param {\n', '    lr_mult: 2\n', '   }\n',
                            '  lpfp_param {\n', '    bd: %i\n' % (layer.bd), '    ad: %i\n' % (
                                              layer.ad), '    round_bias: %s\n' % (layer.round_bias), '  }\n',
                            '  inner_product_param {\n', '    num_output: %s\n' % (
                                              layer.output),
                            '  }\n',
                            '}\n']
                    else:
                        lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                          '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                            layer.name, layer.counter),
                            '  param {\n', '    lr_mult: 1\n', '   }\n',
                            '  param {\n', '    lr_mult: 2\n', '   }\n',
                            '  inner_product_param {\n', '    num_output: %s\n' % (
                                              layer.output),
                            '  }\n',
                            '}\n']
                else:
                    if init_method == 'gaussian':
                        if lp:
                            layer.name += '_lp'
                            layer.type = 'LPInnerProduct'
                            lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                              '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                                layer.name, layer.counter),
                                '  param {\n', '    lr_mult: 1\n', '    decay_mult: 1\n', '   }\n',
                                '  param {\n', '    lr_mult: 2\n', '    decay_mult: 0\n', '   }\n',
                                '  lpfp_param {\n', '    bd: %i\n' % (layer.bd), '    ad: %i\n' % (
                                                  layer.ad), '    round_bias: %s\n' % (layer.round_bias), '  }\n',
                                '  inner_product_param {\n', '    num_output: %s\n' % (
                                                  layer.output),
                                '    weight_filler {\n', '      type: "gaussian"\n', '      std: 0.005\n', '  }\n',
                                '    bias_filler {\n', '      type: "constant"\n', '      value: 0.1\n', '   }\n',
                                '  }\n',
                                '}\n']
                        else:
                            lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                              '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                                layer.name, layer.counter),
                                '  param {\n', '    lr_mult: 1\n', '    decay_mult: 1\n', '   }\n',
                                '  param {\n', '    lr_mult: 2\n', '    decay_mult: 0\n', '   }\n',
                                '  inner_product_param {\n', '    num_output: %s\n' % (
                                                  layer.output),
                                '    weight_filler {\n', '      type: "gaussian"\n', '      std: 0.005\n', '   }\n',
                                '    bias_filler {\n', '      type: "constant"\n', '      value: 0.1\n', '   }\n',
                                '  }\n',
                                '}\n']
                    if init_method == 'xavier':
                        if lp:
                            layer.name += '_lp'
                            layer.type = 'LPInnerProduct'
                            lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                              '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                                layer.name, layer.counter),
                                '  param {\n', '    lr_mult: 1\n', '    decay_mult: 1\n', '   }\n',
                                '  param {\n', '    lr_mult: 2\n', '    decay_mult: 0\n', '   }\n',
                                '  lpfp_param {\n', '    bd: %i\n' % (layer.bd), '    ad: %i\n' % (
                                                  layer.ad), '    round_bias: %s\n' % (layer.round_bias), '  }\n',
                                '  inner_product_param {\n', '    num_output: %s\n' % (
                                                  layer.output),
                                '    weight_filler {\n', '      type: "xavier"\n', '  }\n',
                                '    bias_filler {\n', '      type: "constant"\n', '      value: 0.1\n', '   }\n',
                                '  }\n',
                                '}\n']
                        else:
                            lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                              '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                                layer.name, layer.counter),
                                '  param {\n', '    lr_mult: 1\n', '    decay_mult: 1\n', '   }\n',
                                '  param {\n', '    lr_mult: 2\n', '    decay_mult: 0\n', '   }\n',
                                '  inner_product_param {\n', '    num_output: %s\n' % (
                                                  layer.output),
                                '    weight_filler {\n', '      type: "xavier"\n', '   }\n',
                                '    bias_filler {\n', '      type: "constant"\n', '      value: 0.1\n', '   }\n',
                                '  }\n',
                                '}\n']

                layer_base.writelines(lines_to_write)
            if 'D' in cLayer:
                # print 'Dropout'
                layer.name = 'drop'
                layer.type = 'Dropout'
                layer.dropout_rate = cLayer.partition("D")[2]
                lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                  '  bottom: "%s"\n' % (
                    layer.name_old), '  top: "%s"\n' % (layer.name_old),
                    '  dropout_param {\n', '    dropout_ratio: 0.%s\n' % (
                    layer.dropout_rate), '  }\n',
                    '}\n']
                layer_base.writelines(lines_to_write)

            if cLayer == 'Accuracy':
                # print 'Accuracy'
                layer.name = 'accuracy'
                layer.type = 'Accuracy'
                lines_to_write = ['layer {\n', '  name: "%s"\n' % (layer.name), '  type: "%s"\n' % (layer.type), '  bottom: "%s"\n' % (layer.name_old),
                                  '  bottom: "label"\n', '  top: "%s"\n' % (
                    layer.name),
                    '  include {\n', '    phase: TEST\n', '  }\n',
                    '}\n']
                if deploy:
                    layer_name = 'accuracy_top5'
                    lines_to_write = ['layer {\n', '  name: "%s"\n' % (layer.name), '  type: "%s"\n' % (layer.type), '  bottom: "%s"\n' % (layer.name_old),
                                      '  bottom: "label"\n', '  top: "%s"\n' % (
                        layer.name),
                        '  include {\n', '    phase: TEST\n', '  }\n',
                        '}\n'
                        'layer {\n', '  name: "%s"\n' % (layer_name), '  type: "%s"\n' % (
                                          layer.type), '  bottom: "%s"\n' % (layer.name_old),
                        '  bottom: "label"\n', '  top: "%s"\n' % (
                                          layer_name),
                        '  include {\n', '    phase: TEST\n', '  }\n',
                        '  accuracy_param {\n', '    top_k: 5\n', '  }\n',
                        '}\n']
                layer_base.writelines(lines_to_write)

            if cLayer == 'loss':
                # print 'Loss'
                layer.name = 'loss'
                layer.type = 'SoftmaxWithLoss'
                lines_to_write = ['layer {\n', '  name: "%s"\n' % (layer.name), '  type: "%s"\n' % (layer.type), '  bottom: "%s"\n' % (layer.name_old),
                                  '  bottom: "label"\n', '  top: "%s"\n' % (
                    layer.name),
                    '}\n']
                layer_base.writelines(lines_to_write)
            if cLayer == 'norm':
                layer.name = 'norm'
                layer.type = 'LRN'
                lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                  '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                    layer.name, layer.counter),
                    '  lrn_param {\n', '    local_size: 5\n', '    alpha: 0.0001\n', '    beta: 0.75\n', '  }\n',
                    '}\n']
                layer_base.writelines(lines_to_write)
            if cLayer == 'bnorm':
                layer.name = 'bn'
                layer.type = 'BatchNorm'
                lines_to_write = ['layer {\n', '  name: "%s_%i"\n' % (layer.name, layer.counter), '  type: "%s"\n' % (layer.type),
                                  '  bottom: "%s"\n' % (layer.name_old), '  top: "%s_%i"\n' % (
                    layer.name, layer.counter),
                    '  param {\n', '    lr_mult: 0\n', '  }\n',
                    '  param {\n', '    lr_mult: 0\n', '  }\n',
                    '  param {\n', '    lr_mult: 0\n', '  }\n',
                    '}\n']
                layer_base.writelines(lines_to_write)

            update = True
            if cLayer == "ReLU":
                update = False
            if cLayer == "D5":
                update = False
            if cLayer == "Accuracy":
                update = False
            if cLayer == "loss":
                update = False
            if update:
                layer.name_old = layer.name + '_' + str(layer.counter)
                layer.counter += 1

            layer_base.close()
        # To include the standard header, which handles directories and the input data
        # we need to write first the header and afterwards the layer_basis into
        # new prototxt
        if lp:
            if deploy:
                header = open(self.layer_dir + 'header_deploy.prototxt', 'r')
                if visualize:
                    header = open(self.layer_dir + 'header_vis.prototxt', 'r')
            else:
                header = open(self.layer_dir + 'header.prototxt', 'r')
        else:
            if deploy:
                header = open(
                    self.layer_dir + 'header_deploy_noscale.prototxt', 'r')
                if visualize:
                    header = open(
                        self.layer_dir + 'header_vis_noscale.prototxt', 'r')
            else:
                header = open(self.layer_dir + 'header_noscale.prototxt', 'r')

        base = open(self.layer_dir + 'layer_base.prototxt', 'r')
        net = open(self.save_dir + filename, "w")
        net.write(header.read() + '\n')
        net.write(base.read())

        header.close()
        net.close()
